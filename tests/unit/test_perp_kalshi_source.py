"""`KalshiPerpMarkSource` / `parse_margin_market` against the live
`/margin/markets` payload shape captured 2026-09-07 (kxbtc15m-validation-
rebuild §5 data capture).
"""

from __future__ import annotations

import pytest

from kalshi_bot.data.perps.kalshi_source import KalshiPerpMarkSource, parse_margin_market
from kalshi_bot.execution.kalshi_client import KalshiAuthError

# trimmed from the live probe
LIVE_BTC_ENTRY = {
    "ticker": "KXBTCPERP",
    "asset_class": "Crypto",
    "bid": "7.9174",
    "ask": "7.9177",
    "contract_size": "0.000100",
    "leverage_estimate": 5.9492,
    "open_interest": "1244117.00",
    "price": "7.9174",
    "reference_price": {"price": "7.9161", "ts_ms": 1788766838000},
    "settlement_mark_price": {"price": "7.9186", "ts_ms": 1788766837769},
    "liquidation_mark_price": {"price": "7.9177", "ts_ms": 1788766838100},
    "status": "active",
}


def test_parses_the_live_margin_market_shape():
    r = parse_margin_market(LIVE_BTC_ENTRY)
    assert r is not None
    assert r.market_ticker == "KXBTCPERP"
    assert r.observed_at == 1788766837  # ts_ms // 1000, floor
    assert r.settlement_mark == "7.9186"
    assert r.reference_price == "7.9161"
    assert r.liquidation_mark == "7.9177"
    assert r.bid == "7.9174"
    assert r.ask == "7.9177"
    assert r.contract_size == "0.000100"
    assert r.leverage_estimate == pytest.approx(5.9492)
    assert r.available_at is None  # poll loop stamps receipt


@pytest.mark.parametrize(
    "entry",
    [
        "not a dict",
        {"asset_class": "Crypto"},  # no ticker
        {"ticker": "KXBTCPERP"},  # no settlement mark
        {"ticker": "KXBTCPERP", "settlement_mark_price": {"price": "7.9"}},  # no ts_ms
        {"ticker": "KXBTCPERP", "settlement_mark_price": {"ts_ms": 1788766837769}},  # no price
        {"ticker": "KXBTCPERP", "settlement_mark_price": {"price": "0", "ts_ms": 1788766837769}},
        {"ticker": "KXBTCPERP", "settlement_mark_price": {"price": "-1", "ts_ms": 1788766837769}},
    ],
)
def test_unusable_entries_return_none(entry):
    assert parse_margin_market(entry) is None


class _FakeClient:
    def __init__(self, body: object, *, raises: BaseException | None = None) -> None:
        self._body = body
        self._raises = raises

    def get_markets(self, *, status: str | None = None) -> dict:
        if self._raises is not None:
            raise self._raises
        assert isinstance(self._body, dict)
        return self._body


def test_fetch_returns_one_reading_per_wanted_ticker():
    body = {
        "markets": [
            LIVE_BTC_ENTRY,
            {**LIVE_BTC_ENTRY, "ticker": "KXETHPERP"},
            {**LIVE_BTC_ENTRY, "ticker": "KXAAVEPERP"},
        ]
    }
    src = KalshiPerpMarkSource(_FakeClient(body), tickers=["KXBTCPERP", "KXETHPERP"])
    got = {r.market_ticker for r in src.fetch()}
    assert got == {"KXBTCPERP", "KXETHPERP"}


def test_fetch_swallows_transient_errors_as_empty():
    src = KalshiPerpMarkSource(
        _FakeClient(None, raises=RuntimeError("timeout")), tickers=["KXBTCPERP"]
    )
    assert list(src.fetch()) == []


def test_fetch_reraises_auth_failure():
    src = KalshiPerpMarkSource(
        _FakeClient(None, raises=KalshiAuthError("401")), tickers=["KXBTCPERP"]
    )
    with pytest.raises(KalshiAuthError):
        src.fetch()


def test_requires_at_least_one_ticker():
    with pytest.raises(ValueError):
        KalshiPerpMarkSource(_FakeClient({"markets": []}), tickers=[])
