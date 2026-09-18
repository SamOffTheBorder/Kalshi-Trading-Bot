"""Foreground public-trade poll (public_trade_imbalance experiment data
capture): causal timestamps, per-ticker dedup / gap / resume, honest empty
ticks, clean interrupt. The trade-stream analogue of `test_perp_mark_poll.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.public_trades.poll import (
    CallableTradeSource,
    TradeReadingRaw,
    poll_public_trades,
)
from kalshi_bot.storage.models import Base, PublicTrade


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


class _ScriptedSource:
    """Yields one batch of readings per `fetch()` call from a script,
    ignoring the `since_by_ticker` argument (tests script the readings
    directly rather than filtering)."""

    name = "test:trades"

    def __init__(self, batches: list[list[TradeReadingRaw]]) -> None:
        self._batches = list(batches)
        self._i = 0

    def fetch(self, since_by_ticker: dict[str, int | None]) -> list[TradeReadingRaw]:
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch


def _reading(
    ticker: str, trade_id: str, observed_at: int, *, price: str = "0.31"
) -> TradeReadingRaw:
    return TradeReadingRaw(
        market_ticker=ticker,
        trade_id=trade_id,
        observed_at=observed_at,
        price_dollars=price,
        quantity_fp="100.00",
        taker_side="yes",
    )


def _clock(start: float, step: float):
    t = {"v": start}

    def now() -> float:
        return t["v"]

    def sleep(dt: float) -> None:
        t["v"] += max(dt, step)

    return now, sleep


def test_persists_trades_with_causal_timestamps(session):
    src = _ScriptedSource(
        [[_reading("KXBTC15M-A", "t1", 1_000_000), _reading("KXBTC15M-B", "t2", 1_000_000)]]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=120, session_id="sess-1",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    rows = session.execute(select(PublicTrade)).scalars().all()
    assert {r.market_ticker for r in rows} == {"KXBTC15M-A", "KXBTC15M-B"}
    for r in rows:
        assert r.observed_at == 1_000_000
        assert r.available_at >= r.observed_at
        assert r.price_dollars == "0.31"
        assert r.capture_session_id == "sess-1"
        assert r.provenance["operator_run"] is True


def test_duplicate_trade_id_is_skipped(session):
    src = _ScriptedSource(
        [
            [_reading("KXBTC15M-A", "t1", 1_000_060)],
            [_reading("KXBTC15M-A", "t1", 1_000_060)],  # same trade id re-seen
            [_reading("KXBTC15M-A", "t2", 1_000_120)],
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    assert result.duplicates_skipped == 1
    ids = sorted(r.trade_id for r in session.execute(select(PublicTrade)).scalars())
    assert ids == ["t1", "t2"]


def test_gap_is_recorded_not_filled(session):
    src = _ScriptedSource(
        [
            [_reading("KXBTC15M-A", "t1", 1_000_000)],
            [_reading("KXBTC15M-A", "t2", 1_000_600)],  # 600s jump, threshold 150s
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.gaps_observed == 1
    assert result.persisted == 2
    ts = sorted(r.observed_at for r in session.execute(select(PublicTrade)).scalars())
    assert ts == [1_000_000, 1_000_600]


def test_resume_reads_each_tickers_own_last_observed_at(session):
    session.add(
        PublicTrade(
            market_ticker="KXBTC15M-A", observed_at=1_000_500, available_at=1_000_500,
            price_dollars="0.5", quantity_fp="1.0", trade_id="old1",
            capture_session_id="old",
        )
    )
    session.commit()
    src = _ScriptedSource(
        [
            [
                _reading("KXBTC15M-A", "t-old", 1_000_400),  # older -> skip
                _reading("KXBTC15M-B", "t-new", 1_000_400),  # new ticker -> persist
            ],
            [_reading("KXBTC15M-A", "t-fresh", 1_000_900)],  # newer -> persist + gap
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.duplicates_skipped == 1
    assert result.persisted == 2
    assert result.gaps_observed == 1


def test_same_timestamp_different_trade_ids_both_persist(session):
    # Multiple trades can legitimately share an observed_at second; dedup is
    # by trade_id, not solely by timestamp advancing.
    src = _ScriptedSource(
        [[_reading("KXBTC15M-A", "t1", 1_000_000), _reading("KXBTC15M-A", "t2", 1_000_000)]]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=60, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2


def test_empty_fetch_is_a_skipped_tick(session):
    src = _ScriptedSource([[], [], []])
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=180, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 0
    assert result.empty_ticks >= 1
    assert session.execute(select(PublicTrade)).scalars().first() is None


def test_source_exception_is_swallowed_and_counted(session):
    class _Boom:
        name = "boom"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, since_by_ticker):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return [_reading("KXBTC15M-A", f"t{self.calls}", 1_000_000 + self.calls)]

    src = _Boom()
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, src, interval_s=60, duration_s=180, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.errors == 1
    assert result.persisted >= 1


def test_interrupt_stops_cleanly(session):
    class _Interrupts:
        name = "kbint"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self, since_by_ticker):
            self.calls += 1
            if self.calls == 1:
                return [_reading("KXBTC15M-A", "t1", 1_000_060)]
            raise KeyboardInterrupt

    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_public_trades(
        session, _Interrupts(), interval_s=60, duration_s=6000, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.stopped_reason == "interrupted"
    assert result.persisted == 1
    assert session.execute(select(PublicTrade)).scalars().first() is not None


def test_rejects_bad_intervals(session):
    src = CallableTradeSource(lambda since: [], name="x")
    with pytest.raises(ValueError):
        poll_public_trades(session, src, interval_s=0, duration_s=60, session_id="s")
    with pytest.raises(ValueError):
        poll_public_trades(session, src, interval_s=60, duration_s=0, session_id="s")
