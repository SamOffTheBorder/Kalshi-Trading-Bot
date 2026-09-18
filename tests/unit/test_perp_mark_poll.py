"""Foreground perp mark-price poll (kxbtc15m-validation-rebuild §5 data
capture): causal timestamps, per-ticker dedup / gap / resume, honest empty
ticks, clean interrupt. The perp analogue of `test_brti_poll.py`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.perps.mark_poll import (
    CallablePerpMarkSource,
    PerpMarkReadingRaw,
    poll_perp_marks,
)
from kalshi_bot.storage.models import Base, PerpMarkObservation


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


class _ScriptedSource:
    """Yields one batch of readings per `fetch()` call from a script."""

    name = "test:perp-marks"

    def __init__(self, batches: list[list[PerpMarkReadingRaw]]) -> None:
        self._batches = list(batches)
        self._i = 0

    def fetch(self) -> list[PerpMarkReadingRaw]:
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch


def _reading(ticker: str, observed_at: int, mark: str = "8.0000") -> PerpMarkReadingRaw:
    return PerpMarkReadingRaw(
        market_ticker=ticker,
        observed_at=observed_at,
        settlement_mark=mark,
        reference_price="8.0010",
        liquidation_mark="7.9000",
        bid="7.9990",
        ask="8.0010",
        contract_size="0.000100",
        open_interest="1244117.00",
        leverage_estimate=5.9,
    )


def _clock(start: float, step: float):
    t = {"v": start}

    def now() -> float:
        return t["v"]

    def sleep(dt: float) -> None:
        t["v"] += max(dt, step)

    return now, sleep


def test_persists_marks_with_causal_timestamps(session):
    src = _ScriptedSource(
        [[_reading("KXBTCPERP", 1_000_000), _reading("KXETHPERP", 1_000_000)]]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, src, interval_s=60, duration_s=120, session_id="sess-1",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    rows = session.execute(select(PerpMarkObservation)).scalars().all()
    assert {r.market_ticker for r in rows} == {"KXBTCPERP", "KXETHPERP"}
    for r in rows:
        assert r.observed_at == 1_000_000
        # available_at is never earlier than observed_at
        assert r.available_at >= r.observed_at
        assert r.settlement_mark_dollars == "8.0000"
        assert r.capture_session_id == "sess-1"
        assert r.provenance["operator_run"] is True


def test_stale_mark_timestamp_is_skipped(session):
    # second batch's KXBTCPERP has an observed_at <= the first -> skipped;
    # a fresh one is persisted.
    src = _ScriptedSource(
        [
            [_reading("KXBTCPERP", 1_000_060)],
            [_reading("KXBTCPERP", 1_000_060, mark="9.9999")],  # not advanced
            [_reading("KXBTCPERP", 1_000_120, mark="8.1111")],
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 2
    assert result.duplicates_skipped == 1
    marks = sorted(
        r.settlement_mark_dollars
        for r in session.execute(select(PerpMarkObservation)).scalars()
    )
    assert marks == ["8.0000", "8.1111"]


def test_gap_is_recorded_not_filled(session):
    src = _ScriptedSource(
        [
            [_reading("KXBTCPERP", 1_000_000)],
            [_reading("KXBTCPERP", 1_000_600)],  # 600s jump, threshold 150s
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.gaps_observed == 1
    assert result.persisted == 2  # both real readings kept; nothing fabricated between
    ts = sorted(
        r.observed_at for r in session.execute(select(PerpMarkObservation)).scalars()
    )
    assert ts == [1_000_000, 1_000_600]


def test_resume_reads_each_tickers_own_last_observed_at(session):
    session.add(
        PerpMarkObservation(
            market_ticker="KXBTCPERP", observed_at=1_000_500, available_at=1_000_500,
            settlement_mark_dollars="8.0", source="prior", capture_session_id="old",
        )
    )
    session.commit()
    src = _ScriptedSource(
        [
            [
                _reading("KXBTCPERP", 1_000_400),  # older than the stored row -> skip
                _reading("KXETHPERP", 1_000_400),  # new ticker -> persist
            ],
            [_reading("KXBTCPERP", 1_000_900)],  # newer -> persist (and a gap vs 1_000_500)
        ]
    )
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, src, interval_s=60, duration_s=300, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.duplicates_skipped == 1
    assert result.persisted == 2
    assert result.gaps_observed == 1


def test_empty_fetch_is_a_skipped_tick(session):
    src = _ScriptedSource([[], [], []])
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, src, interval_s=60, duration_s=180, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.persisted == 0
    assert result.empty_ticks >= 1
    assert session.execute(select(PerpMarkObservation)).scalars().first() is None


def test_source_exception_is_swallowed_and_counted(session):
    class _Boom:
        name = "boom"

        def __init__(self) -> None:
            self.calls = 0

        def fetch(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return [_reading("KXBTCPERP", 1_000_000 + self.calls)]

    src = _Boom()
    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
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
                return [_reading("KXBTCPERP", 1_000_060)]
            raise KeyboardInterrupt

    now, sleep = _clock(1_000_000.0, 60.0)
    result = poll_perp_marks(
        session, _Interrupts(), interval_s=60, duration_s=6000, session_id="s",
        now_fn=now, sleep_fn=sleep,
    )
    assert result.stopped_reason == "interrupted"
    assert result.persisted == 1
    assert session.execute(select(PerpMarkObservation)).scalars().first() is not None


def test_rejects_bad_intervals(session):
    src = CallablePerpMarkSource(lambda: [], name="x")
    with pytest.raises(ValueError):
        poll_perp_marks(session, src, interval_s=0, duration_s=60, session_id="s")
    with pytest.raises(ValueError):
        poll_perp_marks(session, src, interval_s=60, duration_s=0, session_id="s")
