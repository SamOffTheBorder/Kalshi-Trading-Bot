"""Foreground L2 order-book poll (microprice experiment data capture):
causal timestamps, per-ticker dedup / gap / resume, honest empty ticks,
clean interrupt. The L2 analogue of `test_perp_mark_poll.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.l2.poll import CallableL2Source, L2ReadingRaw, poll_l2
from kalshi_bot.storage.models import Base, OrderBookSnapshot


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


class _ScriptedSource:
    """Yields one batch of readings per `fetch()` call from a script."""

    name = "test:l2"

    def __init__(self, batches: list[list[L2ReadingRaw]]) -> None:
        self._batches = list(batches)
        self._i = 0

    def fetch(self) -> list[L2ReadingRaw]:
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch


def _reading(
    ticker: str, *, observed_at: int | None = None, bid: str = "0.30", ask: str = "0.31"
) -> L2ReadingRaw:
    return L2ReadingRaw(
        market_ticker=ticker,
        bids=[[bid, "100"]],
        asks=[[ask, "150"]],
        observed_at=observed_at,
    )


def _clock(start: float, step: float):
    t = {"v": start}

    def now() -> float:
        return t["v"]

    def sleep(dt: float) -> None:
        t["v"] += max(dt, step)

    return now, sleep


def test_persists_snapshots_with_causal_timestamps_from_receipt(session):
    # Kalshi's orderbook response has no server timestamp -- observed_at and
    # available_at both come from local receipt time.
    src = _ScriptedSource([[_reading("KXBTC15M-A"), _reading("KXBTC15M-B")]])
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, src, interval_s=60, duration_s=120, session_id="sess-1",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    rows = session.execute(select(OrderBookSnapshot)).scalars().all()
    assert {r.market_ticker for r in rows} == {"KXBTC15M-A", "KXBTC15M-B"}
    for r in rows:
        assert r.observed_at == 1_000_000
        assert r.available_at >= r.observed_at
        assert r.bids == [["0.30", "100"]]
        assert r.asks == [["0.31", "150"]]
        assert r.capture_session_id == "sess-1"
        assert r.provenance["operator_run"] is True


def test_duplicate_tick_timestamp_is_skipped(session):
    src = _ScriptedSource(
        [
            [_reading("KXBTC15M-A", observed_at=1_000_060)],
            [_reading("KXBTC15M-A", observed_at=1_000_060, bid="0.40")],  # not advanced
            [_reading("KXBTC15M-A", observed_at=1_000_120, bid="0.45")],
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    assert result.duplicates_skipped == 1
    bids = sorted(
        r.bids[0][0] for r in session.execute(select(OrderBookSnapshot)).scalars()
    )
    assert bids == ["0.30", "0.45"]


def test_gap_is_recorded_not_filled(session):
    src = _ScriptedSource(
        [
            [_reading("KXBTC15M-A", observed_at=1_000_000)],
            [_reading("KXBTC15M-A", observed_at=1_000_600)],  # 600s jump, threshold 150s
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.gaps_observed == 1
    assert result.persisted == 2
    ts = sorted(
        r.observed_at for r in session.execute(select(OrderBookSnapshot)).scalars()
    )
    assert ts == [1_000_000, 1_000_600]


def test_resume_reads_each_tickers_own_last_observed_at(session):
    session.add(
        OrderBookSnapshot(
            market_ticker="KXBTC15M-A", observed_at=1_000_500, available_at=1_000_500,
            bids=[["0.20", "1"]], asks=[["0.21", "1"]], capture_session_id="old",
        )
    )
    session.commit()
    src = _ScriptedSource(
        [
            [
                _reading("KXBTC15M-A", observed_at=1_000_400),  # older -> skip
                _reading("KXBTC15M-B", observed_at=1_000_400),  # new ticker -> persist
            ],
            [_reading("KXBTC15M-A", observed_at=1_000_900)],  # newer -> persist + gap
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.duplicates_skipped == 1
    assert result.persisted == 2
    assert result.gaps_observed == 1


def test_missing_observed_at_falls_back_to_receipt_time(session):
    src = _ScriptedSource([[_reading("KXBTC15M-A", observed_at=None)]])
    now, sleep = _clock(1_000_000.0, 60.0)
    poll_l2(
        session, src, interval_s=60, duration_s=60, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    row = session.execute(select(OrderBookSnapshot)).scalars().one()
    assert row.observed_at == 1_000_000
    assert row.available_at == 1_000_000


def test_empty_fetch_is_a_skipped_tick(session):
    src = _ScriptedSource([[], [], []])
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, src, interval_s=60, duration_s=180, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 0
    assert result.empty_ticks >= 1
    assert session.execute(select(OrderBookSnapshot)).scalars().first() is None


def test_source_exception_is_swallowed_and_counted(session):
    class _Boom:
        name = "boom"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return [_reading("KXBTC15M-A", observed_at=1_000_000 + self.calls)]

    src = _Boom()
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
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

        def fetch(self):
            self.calls += 1
            if self.calls == 1:
                return [_reading("KXBTC15M-A", observed_at=1_000_060)]
            raise KeyboardInterrupt

    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_l2(
        session, _Interrupts(), interval_s=60, duration_s=6000, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.stopped_reason == "interrupted"
    assert result.persisted == 1
    assert session.execute(select(OrderBookSnapshot)).scalars().first() is not None


def test_rejects_bad_intervals(session):
    src = CallableL2Source(lambda: [], name="x")
    with pytest.raises(ValueError):
        poll_l2(session, src, interval_s=0, duration_s=60, session_id="s")
    with pytest.raises(ValueError):
        poll_l2(session, src, interval_s=60, duration_s=0, session_id="s")
