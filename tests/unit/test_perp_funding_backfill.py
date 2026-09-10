"""One-shot Kalshi crypto-perp funding-history backfill
(kxbtc15m-validation-rebuild §5 data capture): idempotent writes, a zero
funding rate is a real observation, malformed rows are skipped, one ticker's
failure does not stop the rest, and windowing is respected.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.perps.funding import (
    backfill_funding,
    capture_funding_estimates,
    resolve_crypto_perp_tickers,
)
from kalshi_bot.storage.models import Base, PerpFundingEstimateObservation, PerpFundingObservation

# 2026-09-06T04:00:00Z .. 2026-09-07T04:00:00Z, 8h spacing
T0 = 1_788_753_600  # 2026-09-07T04:00:00Z per the live probe
DAY = 86_400


class _FakeMarginClient:
    def __init__(
        self, *, rows_by_ticker: dict | None = None, markets: list | None = None,
        estimates_by_ticker: dict | None = None, raises_for: tuple[str, ...] = (),
    ) -> None:
        self._rows = rows_by_ticker or {}
        self._markets = markets or []
        self._estimates = estimates_by_ticker or {}
        self._raises_for = set(raises_for)

    def get_historical_funding_rates(
        self, *, ticker: str | None = None, start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> dict:
        if ticker in self._raises_for:
            raise RuntimeError("boom")
        return {"funding_rates": list(self._rows.get(ticker, []))}

    def get_markets(self, *, status: str | None = None) -> dict:
        return {"markets": list(self._markets)}

    def get_funding_rate_estimate(self, ticker: str) -> dict:
        if ticker in self._raises_for:
            raise RuntimeError("boom")
        return dict(self._estimates.get(ticker, {}))


def _row(ticker, iso, rate, mark="7.96"):
    return {
        "market_ticker": ticker,
        "funding_time": iso,
        "funding_rate": rate,
        "mark_price": mark,
    }


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


def test_backfills_and_is_idempotent(session):
    client = _FakeMarginClient(
        rows_by_ticker={
            "KXBTCPERP": [
                _row("KXBTCPERP", "2026-09-07T04:00:00Z", 0.000135),
                _row("KXBTCPERP", "2026-09-06T20:00:00Z", 0.0),  # a real 0
                _row("KXBTCPERP", "2026-09-06T12:00:00Z", 0.00011),
            ]
        }
    )
    r1 = backfill_funding(
        session, client, tickers=["KXBTCPERP"],
        start_ts=T0 - 2 * DAY, end_ts=T0 + DAY, session_id="s1",
    )
    assert r1.persisted == 3
    rows = session.execute(select(PerpFundingObservation)).scalars().all()
    assert len(rows) == 3
    assert sorted(x.funding_rate for x in rows) == [0.0, 0.00011, 0.000135]
    # every row: available_at == observed_at (no fabricated earlier availability)
    for x in rows:
        assert x.available_at == x.observed_at

    # second run over the same window writes nothing new
    r2 = backfill_funding(
        session, client, tickers=["KXBTCPERP"],
        start_ts=T0 - 2 * DAY, end_ts=T0 + DAY, session_id="s2",
    )
    assert r2.persisted == 0
    assert r2.duplicates_skipped == 3
    assert session.execute(select(PerpFundingObservation)).scalars().all().__len__() == 3


def test_rows_outside_the_window_are_ignored(session):
    client = _FakeMarginClient(
        rows_by_ticker={
            "KXETHPERP": [
                _row("KXETHPERP", "2026-09-07T04:00:00Z", 0.0002),
                _row("KXETHPERP", "2026-08-01T04:00:00Z", 0.0003),  # way before start
            ]
        }
    )
    r = backfill_funding(
        session, client, tickers=["KXETHPERP"],
        start_ts=T0 - DAY, end_ts=T0 + DAY, session_id="s",
    )
    assert r.persisted == 1


def test_malformed_rows_are_skipped_not_fatal(session):
    client = _FakeMarginClient(
        rows_by_ticker={
            "KXSOLPERP": [
                _row("KXSOLPERP", "2026-09-07T04:00:00Z", 0.0001),
                {"market_ticker": "KXSOLPERP", "funding_time": "not-a-date", "funding_rate": 0.1},
                {"market_ticker": "KXSOLPERP", "funding_rate": 0.1},  # no time
                "totally wrong",
            ]
        }
    )
    r = backfill_funding(
        session, client, tickers=["KXSOLPERP"],
        start_ts=T0 - DAY, end_ts=T0 + DAY, session_id="s",
    )
    assert r.persisted == 1
    assert r.malformed_skipped == 3


def test_one_ticker_failure_does_not_stop_the_rest(session):
    client = _FakeMarginClient(
        rows_by_ticker={
            "KXDOGEPERP": [_row("KXDOGEPERP", "2026-09-07T04:00:00Z", 0.0005)],
        },
        raises_for=("KXBTCPERP",),
    )
    r = backfill_funding(
        session, client, tickers=["KXBTCPERP", "KXDOGEPERP"],
        start_ts=T0 - DAY, end_ts=T0 + DAY, session_id="s",
    )
    assert r.errors == 1
    assert r.persisted == 1


def test_resolve_crypto_perp_tickers_filters_to_wanted_assets(session):
    client = _FakeMarginClient(
        markets=[
            {"ticker": "KXBTCPERP", "asset_class": "Crypto", "status": "active"},
            {"ticker": "KXETHPERP", "asset_class": "Crypto", "status": "active"},
            {"ticker": "KXAAVEPERP", "asset_class": "Crypto", "status": "active"},
            {"ticker": "KXSPYPERP", "asset_class": "Equity", "status": "active"},
            {"ticker": "SOME-EVENT", "asset_class": "Crypto", "status": "active"},
        ]
    )
    assert resolve_crypto_perp_tickers(client, wanted=["BTC", "ETH"]) == [
        "KXBTCPERP",
        "KXETHPERP",
    ]
    # no filter -> every active crypto perp
    assert set(resolve_crypto_perp_tickers(client)) == {
        "KXBTCPERP",
        "KXETHPERP",
        "KXAAVEPERP",
    }


def test_captures_current_funding_estimate_idempotently(session):
    client = _FakeMarginClient(
        estimates_by_ticker={
            "KXBTCPERP": {
                "market_ticker": "KXBTCPERP",
                "computed_time": "2026-09-07T05:01:02Z",
                "funding_rate": "0.000135",
                "mark_price": "7.96",
                "next_funding_time": "2026-09-07T12:00:00Z",
            }
        }
    )
    result = capture_funding_estimates(
        session, client, tickers=["KXBTCPERP"], session_id="s1", now_fn=lambda: T0 + 7200
    )
    assert result.persisted == 1
    row = session.execute(select(PerpFundingEstimateObservation)).scalar_one()
    assert row.funding_rate == pytest.approx(0.000135)
    assert row.mark_price_dollars == "7.96"
    assert row.next_funding_time == "2026-09-07T12:00:00Z"
    assert row.available_at >= row.observed_at

    repeated = capture_funding_estimates(
        session, client, tickers=["KXBTCPERP"], session_id="s2", now_fn=lambda: T0 + 60
    )
    assert repeated.persisted == 0
    assert repeated.duplicates_skipped == 1


def test_malformed_or_failed_estimates_do_not_stop_other_tickers(session):
    client = _FakeMarginClient(
        estimates_by_ticker={
            "KXETHPERP": {
                "market_ticker": "KXETHPERP",
                "computed_time": "not-a-time",
                "funding_rate": 0.01,
            },
            "KXSOLPERP": {
                "market_ticker": "KXSOLPERP",
                "computed_time": "2026-09-07T05:01:02Z",
                "funding_rate": 0.0,
            },
        },
        raises_for=("KXBTCPERP",),
    )
    result = capture_funding_estimates(
        session,
        client,
        tickers=["KXBTCPERP", "KXETHPERP", "KXSOLPERP"],
        session_id="s",
        now_fn=lambda: T0,
    )
    assert (result.errors, result.malformed_skipped, result.persisted) == (1, 1, 1)
