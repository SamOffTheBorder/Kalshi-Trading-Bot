"""BRTI foreground polling loop (kxbtc15m-validation-rebuild data capture):
causal timestamps, gaps recorded but never filled, resumability across a
restart, and a clean stop on interrupt / duration. Time is fully injected so
these run instantly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from kalshi_bot.data.brti import BRTIReadingRaw, CallableBRTISource, poll_brti
from kalshi_bot.storage.models import Base, BRTIObservation


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


class _Clock:
    """Deterministic monotone clock. `sleep` advances it; `tick` lets the
    caller advance it between polls."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += max(0.0, dt)


def _rows(session: Session) -> list[BRTIObservation]:
    stmt = select(BRTIObservation).order_by(BRTIObservation.observed_at)
    return list(session.execute(stmt).scalars())


def test_persists_readings_with_causal_timestamps(session):
    clock = _Clock()
    seq = iter(
        [
            BRTIReadingRaw(observed_at=1_000_000, value=100_000.0, source="s"),
            BRTIReadingRaw(observed_at=1_000_060, value=100_010.0, source="s"),
            BRTIReadingRaw(observed_at=1_000_120, value=100_020.0, source="s"),
        ]
    )
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    result = poll_brti(
        session, src,
        interval_s=60, duration_s=200, session_id="sess-1",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    rows = _rows(session)
    assert [r.observed_at for r in rows] == [1_000_000, 1_000_060, 1_000_120]
    for r in rows:
        # available_at is stamped from receipt time and can never precede observed_at
        assert r.available_at >= r.observed_at
        assert r.capture_session_id == "sess-1"
        assert r.source == "s"
        assert r.value_dollars == f"{100_000.0 + (r.observed_at - 1_000_000) / 6:.2f}"
    assert result.persisted == 3
    assert result.gaps_observed == 0


def test_low_priced_asset_keeps_precision():
    from kalshi_bot.data.brti.poll import _format_value

    assert _format_value(79_585.27) == "79585.27"
    assert _format_value(2_499.11) == "2499.11"
    assert _format_value(1.4123) == "1.4123"
    assert _format_value(0.093412) == "0.093412"
    assert float(_format_value(0.09341278)) == pytest.approx(0.09341278, rel=1e-6)


def test_respects_source_available_at_when_provided(session):
    clock = _Clock()
    reading = BRTIReadingRaw(
        observed_at=1_000_000, value=100_000.0, source="s", available_at=1_000_003
    )
    seq = iter([reading])
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    poll_brti(
        session, src, interval_s=60, duration_s=90, session_id="x",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )
    (row,) = _rows(session)
    assert row.available_at == 1_000_003  # the source's stated availability, not receipt


def test_gap_is_recorded_not_filled(session):
    clock = _Clock()
    # Two readings 600s apart at a 60s interval -> a gap, and NO synthetic
    # rows inserted to bridge it.
    seq = iter(
        [
            BRTIReadingRaw(observed_at=1_000_000, value=100_000.0, source="s"),
            BRTIReadingRaw(observed_at=1_000_600, value=100_050.0, source="s"),
        ]
    )
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    result = poll_brti(
        session, src, interval_s=60, duration_s=1_000, session_id="g",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    rows = _rows(session)
    assert [r.observed_at for r in rows] == [1_000_000, 1_000_600]  # nothing bridging
    assert result.gaps_observed == 1


def test_empty_ticks_do_not_persist_or_fabricate(session):
    clock = _Clock()
    seq = iter(
        [
            BRTIReadingRaw(observed_at=1_000_000, value=100_000.0, source="s"),
            None,  # source briefly unavailable
            None,
            BRTIReadingRaw(observed_at=1_000_180, value=100_030.0, source="s"),
        ]
    )
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    result = poll_brti(
        session, src, interval_s=60, duration_s=240, session_id="e",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    assert [r.observed_at for r in _rows(session)] == [1_000_000, 1_000_180]
    assert result.empty_ticks == 2  # the two explicit None ticks
    # 180s jump at a 60s interval (threshold 150s) is a gap
    assert result.gaps_observed == 1


def test_resume_after_restart_treats_prior_silence_as_a_gap(session):
    # A prior capture of the SAME feed left a row well in the past. Resume
    # keys on the source label, so the gap is attributed to this feed.
    session.add(
        BRTIObservation(
            observed_at=1_000_000, available_at=1_000_000, value_dollars="99000.00",
            source="s", capture_session_id="old",
        )
    )
    session.commit()

    clock = _Clock(start=1_009_000.0)
    seq = iter([BRTIReadingRaw(observed_at=1_009_000, value=101_000.0, source="s")])
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    result = poll_brti(
        session, src, interval_s=60, duration_s=90, session_id="new",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    assert result.persisted == 1
    assert result.gaps_observed == 1  # the 9000s silence across the restart
    assert result.first_observed_at == 1_009_000


def test_resume_ignores_a_different_feeds_history(session):
    """A prior row from another index must not count as this feed's silence."""
    session.add(
        BRTIObservation(
            observed_at=1_000_000, available_at=1_000_000, value_dollars="42.00",
            source="other-index", capture_session_id="old",
        )
    )
    session.commit()

    clock = _Clock(start=1_009_000.0)
    seq = iter([BRTIReadingRaw(observed_at=1_009_000, value=101_000.0, source="s")])
    src = CallableBRTISource(lambda: next(seq, None), name="s")
    result = poll_brti(
        session, src, interval_s=60, duration_s=90, session_id="new",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )
    assert result.persisted == 1
    assert result.gaps_observed == 0  # not this feed's gap


def test_duplicate_or_stale_observed_at_is_skipped(session):
    clock = _Clock()
    seq = iter(
        [
            BRTIReadingRaw(observed_at=1_000_060, value=100_000.0, source="s"),
            BRTIReadingRaw(observed_at=1_000_060, value=100_001.0, source="s"),  # dup
            BRTIReadingRaw(observed_at=1_000_030, value=99_999.0, source="s"),  # stale
            BRTIReadingRaw(observed_at=1_000_120, value=100_010.0, source="s"),
        ]
    )
    src = CallableBRTISource(lambda: next(seq, None), name="s")

    result = poll_brti(
        session, src, interval_s=60, duration_s=400, session_id="d",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    assert [r.observed_at for r in _rows(session)] == [1_000_060, 1_000_120]
    assert result.duplicates_skipped == 2


def test_source_exception_is_swallowed_and_counted(session):
    clock = _Clock()
    calls = {"n": 0}

    def _fetch() -> BRTIReadingRaw | None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient network error")
        if calls["n"] > 3:
            return None
        return BRTIReadingRaw(observed_at=1_000_000 + calls["n"] * 60, value=100_000.0, source="s")

    src = CallableBRTISource(_fetch, name="s")
    result = poll_brti(
        session, src, interval_s=60, duration_s=300, session_id="err",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    assert result.errors == 1
    assert result.persisted >= 1  # the loop kept going after the exception


def test_interrupt_stops_cleanly(session):
    clock = _Clock()

    def _fetch() -> BRTIReadingRaw:
        raise KeyboardInterrupt

    src = CallableBRTISource(_fetch, name="s")
    result = poll_brti(
        session, src, interval_s=60, duration_s=300, session_id="i",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )
    assert result.stopped_reason == "interrupted"


def test_multiple_sources_each_persist_with_per_index_state(session):
    clock = _Clock()
    btc = iter(
        [
            BRTIReadingRaw(observed_at=1_000_000, value=100_000.0, source="BRTI"),
            BRTIReadingRaw(observed_at=1_000_060, value=100_010.0, source="BRTI"),
        ]
    )
    eth = iter(
        [
            BRTIReadingRaw(observed_at=1_000_000, value=2_500.0, source="ETHUSD_RTI"),
            None,  # eth briefly unavailable on the 2nd tick
        ]
    )
    src_btc = CallableBRTISource(lambda: next(btc, None), name="BRTI")
    src_eth = CallableBRTISource(lambda: next(eth, None), name="ETHUSD_RTI")

    result = poll_brti(
        session, [src_btc, src_eth],
        interval_s=60, duration_s=120, session_id="multi",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )

    rows = _rows(session)
    by_src: dict[str, list[int]] = {}
    for r in rows:
        by_src.setdefault(r.source, []).append(r.observed_at)
    assert by_src["BRTI"] == [1_000_000, 1_000_060]
    assert by_src["ETHUSD_RTI"] == [1_000_000]  # 2nd eth tick was empty
    assert result.persisted == 3
    assert result.empty_ticks == 1
    assert result.polls == 4  # 2 ticks x 2 sources


def test_one_bad_source_does_not_stop_the_others(session):
    clock = _Clock()

    def _bad() -> BRTIReadingRaw:
        raise RuntimeError("index feed down")

    good = iter([BRTIReadingRaw(observed_at=1_000_000, value=100_000.0, source="BRTI")])
    src_good = CallableBRTISource(lambda: next(good, None), name="BRTI")
    result = poll_brti(
        session,
        [CallableBRTISource(_bad, name="BAD"), src_good],
        interval_s=60, duration_s=90, session_id="m",
        now_fn=clock.now, sleep_fn=clock.sleep, commit_every=1,
    )
    assert result.errors >= 1
    assert [r.source for r in _rows(session)] == ["BRTI"]


def test_rejects_empty_source_list(session):
    with pytest.raises(ValueError):
        poll_brti(session, [], interval_s=60, duration_s=10, session_id="x")


def test_rejects_bad_intervals(session):
    src = CallableBRTISource(lambda: None, name="s")
    with pytest.raises(ValueError):
        poll_brti(session, src, interval_s=0, duration_s=10, session_id="x")
    with pytest.raises(ValueError):
        poll_brti(session, src, interval_s=60, duration_s=0, session_id="x")
