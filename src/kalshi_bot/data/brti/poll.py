"""Foreground BRTI polling loop with causal timestamps and honest gap
accounting.

Contract (all four are validation requirements, not nice-to-haves):

1. **Causal timestamps.** Every persisted `BRTIObservation` carries
   `observed_at` (the instant the index value refers to) and `available_at`
   (the instant a live system could first have acted on it). When the source
   only reports one time, `available_at` is set to the local receipt time,
   which is never earlier than `observed_at`.
2. **Gaps are recorded, never filled.** A missing interval leaves a real
   hole in the series. The loop logs it and the `--report` gap analysis
   surfaces it; nothing forward-fills a value as though it had been observed.
3. **Resumable.** On start the loop reads the latest `observed_at` already in
   the table and treats a long silence before the first new reading as a
   gap, so a stop/restart is visible in the record rather than hidden.
4. **Foreground only.** `poll_brti` runs until its `duration_s` elapses or
   the caller interrupts (KeyboardInterrupt is caught and returns a clean
   `PollResult`). It never spawns a thread, schedules a task, or restarts
   itself.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import BRTIObservation


@dataclass(frozen=True)
class BRTIReadingRaw:
    """One index reading straight from a source, before persistence.

    `observed_at` is epoch seconds the value refers to. `available_at` is
    epoch seconds it could first have been acted on; when a source cannot
    distinguish the two it passes `None` and the loop stamps local receipt
    time. `value` is the index level in USD. `source` labels the origin for
    the audit trail (e.g. "cfbenchmarks:BRTI", "kalshi:index").
    """

    observed_at: int
    value: float
    source: str
    available_at: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class BRTISource(Protocol):
    """A pollable BRTI origin. `fetch()` returns the latest single reading,
    or None when the source has nothing new / is briefly unavailable (the
    loop treats None as a skipped tick, i.e. a potential gap — it does not
    raise, retry tightly, or fabricate)."""

    name: str

    def fetch(self) -> BRTIReadingRaw | None: ...


class CallableBRTISource:
    """Adapts a plain ``() -> BRTIReadingRaw | None`` callable to `BRTISource`.
    Used for tests and for wiring a concrete HTTP fetch without a class."""

    def __init__(self, fn: Callable[[], BRTIReadingRaw | None], *, name: str) -> None:
        self._fn = fn
        self.name = name

    def fetch(self) -> BRTIReadingRaw | None:
        return self._fn()


@dataclass
class PollResult:
    polls: int = 0
    persisted: int = 0
    empty_ticks: int = 0
    gaps_observed: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    first_observed_at: int | None = None
    last_observed_at: int | None = None
    stopped_reason: str = "duration_elapsed"

    def as_dict(self) -> dict[str, object]:
        return {
            "polls": self.polls,
            "persisted": self.persisted,
            "empty_ticks": self.empty_ticks,
            "gaps_observed": self.gaps_observed,
            "duplicates_skipped": self.duplicates_skipped,
            "errors": self.errors,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "stopped_reason": self.stopped_reason,
        }


def _format_value(value: float) -> str:
    """Render an index value as a decimal string, keeping precision for
    low-priced assets. BTC at ~$80k needs 2dp; DOGE at ~$0.09 needs ~8sf or
    the reading is meaningless. `value_dollars` is a `String(32)`.
    """
    if value >= 1000:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _latest_observed_at(session: Session, source_label: str) -> int | None:
    return session.scalar(
        select(func.max(BRTIObservation.observed_at)).where(
            BRTIObservation.source == source_label
        )
    )


def poll_brti(
    session: Session,
    sources: BRTISource | Sequence[BRTISource],
    *,
    interval_s: float,
    duration_s: float,
    session_id: str,
    expected_gap_s: float | None = None,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    commit_every: int = 30,
) -> PollResult:
    """Poll one or more index `sources` every `interval_s` seconds for up to
    `duration_s` seconds, persisting each new reading as a `BRTIObservation`.

    Each source is polled once per tick. Dedup and gap accounting are
    per-source (keyed by `source.name`): a stall on one index is that index's
    gap, and resuming reads each index's own latest `observed_at`. A source
    that raises or returns None is a skipped tick for that index only — the
    others still get polled.

    `expected_gap_s` (default: 2.5 x `interval_s`) is the spacing above which
    a jump between consecutive `observed_at` values for one source is logged
    as a gap. Gaps are only ever recorded — never backfilled.

    `now_fn` / `sleep_fn` are injectable so tests run without real time.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    gap_threshold = expected_gap_s if expected_gap_s is not None else interval_s * 2.5
    source_list = [sources] if isinstance(sources, BRTISource) else list(sources)
    if not source_list:
        raise ValueError("at least one source is required")

    result = PollResult()
    prev_by_source: dict[str, int | None] = {}
    for src in source_list:
        prev = _latest_observed_at(session, src.name)
        prev_by_source[src.name] = prev
        if prev is not None:
            logger.info(
                "brti poll resuming for {}; last observed_at is {} — a long silence "
                "before the first new reading is recorded as a gap",
                src.name,
                prev,
            )

    start = now_fn()
    deadline = start + duration_s
    pending = 0
    try:
        while now_fn() < deadline:
            tick_start = now_fn()
            for src in source_list:
                result.polls += 1
                try:
                    reading = src.fetch()
                except Exception as exc:  # one source's hiccup must not stop the rest
                    result.errors += 1
                    logger.warning("brti source {} raised on fetch: {}", src.name, exc)
                    reading = None

                if reading is None:
                    result.empty_ticks += 1
                    continue

                receipt = round(now_fn())
                available_at = max(
                    reading.available_at if reading.available_at is not None else receipt,
                    reading.observed_at,
                )
                label = reading.source or src.name
                prev_observed_at = prev_by_source.get(src.name)

                if prev_observed_at is not None and reading.observed_at <= prev_observed_at:
                    result.duplicates_skipped += 1
                    continue

                if (
                    prev_observed_at is not None
                    and reading.observed_at - prev_observed_at > gap_threshold
                ):
                    result.gaps_observed += 1
                    logger.warning(
                        "brti gap [{}]: {}s between observed_at {} and {} (threshold {}s) — "
                        "recorded as a hole, not filled",
                        label,
                        reading.observed_at - prev_observed_at,
                        prev_observed_at,
                        reading.observed_at,
                        gap_threshold,
                    )
                session.add(
                    BRTIObservation(
                        observed_at=reading.observed_at,
                        available_at=available_at,
                        value_dollars=_format_value(reading.value),
                        source=label,
                        capture_session_id=session_id,
                        source_endpoint=src.name,
                        fetched_at=receipt,
                        provenance={
                            "operator_run": True,
                            "poll_interval_s": interval_s,
                            **reading.extra,
                        },
                    )
                )
                pending += 1
                result.persisted += 1
                result.first_observed_at = result.first_observed_at or reading.observed_at
                result.last_observed_at = reading.observed_at
                prev_by_source[src.name] = reading.observed_at

            if pending >= commit_every:
                session.commit()
                pending = 0

            elapsed = now_fn() - tick_start
            remaining = interval_s - elapsed
            if remaining > 0 and now_fn() + remaining < deadline:
                sleep_fn(remaining)
            elif remaining > 0:
                # Last tick before the deadline — don't oversleep past it.
                sleep_fn(max(0.0, deadline - now_fn()))
    except KeyboardInterrupt:
        result.stopped_reason = "interrupted"
        logger.info("brti poll interrupted by operator")

    session.commit()
    logger.info("brti poll finished: {}", result.as_dict())
    return result


__all__ = [
    "BRTIReadingRaw",
    "BRTISource",
    "CallableBRTISource",
    "PollResult",
    "poll_brti",
]
