"""Foreground poll of Kalshi crypto-perp mark prices, with causal timestamps
and honest gap accounting — the perp analogue of ``brti.poll.poll_brti``.

Kalshi publishes no historical mark-price series for its perpetuals, so the
only way to build one is to snapshot ``GET /margin/markets/{ticker}`` in a
foreground loop. Each snapshot's ``settlement_mark_price`` carries its own
``ts_ms``; that is the reading's ``observed_at``. ``available_at`` is local
receipt time (never earlier than ``observed_at``). A stall between consecutive
snapshots for one ticker is logged as a gap and never backfilled.

Contract, identical in spirit to the BRTI loop:

1. **Causal timestamps** — ``observed_at`` from the exchange mark timestamp,
   ``available_at`` from local receipt.
2. **Gaps recorded, never filled.**
3. **Resumable** — on start, the latest ``observed_at`` already stored per
   ticker is read back, so a stop/restart shows as a gap.
4. **Foreground only** — runs until ``duration_s`` elapses or the operator
   interrupts (``KeyboardInterrupt`` -> clean ``MarkPollResult``). It never
   spawns a thread, schedules a task, or restarts itself.

Read-only: authenticated ``/margin/markets/*`` GET calls, no orders.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import PerpMarkObservation


@dataclass(frozen=True)
class PerpMarkReadingRaw:
    """One perp mark snapshot straight from a source, before persistence.

    ``observed_at`` is epoch seconds the settlement mark refers to.
    ``settlement_mark`` / ``reference_price`` / ``liquidation_mark`` / ``bid``
    / ``ask`` are per-contract dollar strings kept verbatim. ``available_at``
    is ``None`` when the source cannot distinguish it from receipt; the loop
    then stamps local receipt time.
    """

    market_ticker: str
    observed_at: int
    settlement_mark: str
    available_at: int | None = None
    reference_price: str | None = None
    liquidation_mark: str | None = None
    bid: str | None = None
    ask: str | None = None
    contract_size: str | None = None
    open_interest: str | None = None
    leverage_estimate: float | None = None
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class PerpMarkSource(Protocol):
    """A pollable perp-mark origin. ``fetch()`` returns the latest snapshot for
    every ticker it covers (or an empty list when briefly unavailable — the
    loop treats that as a skipped tick, not an error)."""

    name: str

    def fetch(self) -> Sequence[PerpMarkReadingRaw]: ...


class CallablePerpMarkSource:
    """Adapts a ``() -> Sequence[PerpMarkReadingRaw]`` callable to
    ``PerpMarkSource`` — for tests and lightweight wiring."""

    def __init__(
        self, fn: Callable[[], Sequence[PerpMarkReadingRaw]], *, name: str
    ) -> None:
        self._fn = fn
        self.name = name

    def fetch(self) -> Sequence[PerpMarkReadingRaw]:
        return self._fn()


@dataclass
class MarkPollResult:
    polls: int = 0
    persisted: int = 0
    empty_ticks: int = 0
    gaps_observed: int = 0
    duplicates_skipped: int = 0
    errors: int = 0
    tickers_seen: tuple[str, ...] = ()
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
            "tickers_seen": list(self.tickers_seen),
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "stopped_reason": self.stopped_reason,
        }


def _latest_observed_at(session: Session, ticker: str) -> int | None:
    return session.scalar(
        select(func.max(PerpMarkObservation.observed_at)).where(
            PerpMarkObservation.market_ticker == ticker
        )
    )


def poll_perp_marks(
    session: Session,
    source: PerpMarkSource,
    *,
    interval_s: float,
    duration_s: float,
    session_id: str,
    expected_gap_s: float | None = None,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    commit_every: int = 30,
) -> MarkPollResult:
    """Poll ``source`` every ``interval_s`` seconds for up to ``duration_s``
    seconds, persisting each new per-ticker mark snapshot as a
    ``PerpMarkObservation``.

    Dedup and gap accounting are per ticker: a stall on one perp is that
    perp's gap, and resuming reads each ticker's own latest ``observed_at``.
    A snapshot whose ``observed_at`` is <= the last stored one for that ticker
    is skipped (the exchange mark had not advanced yet).

    ``expected_gap_s`` (default ``2.5 * interval_s``) is the spacing above
    which a jump between consecutive ``observed_at`` values for one ticker is
    logged as a gap. Gaps are only recorded, never backfilled.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    gap_threshold = expected_gap_s if expected_gap_s is not None else interval_s * 2.5

    result = MarkPollResult()
    prev_by_ticker: dict[str, int | None] = {}
    seen: list[str] = []

    start = now_fn()
    deadline = start + duration_s
    pending = 0
    try:
        while now_fn() < deadline:
            tick_start = now_fn()
            result.polls += 1
            try:
                readings = list(source.fetch())
            except Exception as exc:  # a transient source failure is a skipped tick
                result.errors += 1
                logger.warning("perp mark source {} raised: {}", source.name, exc)
                readings = []

            if not readings:
                result.empty_ticks += 1
            for reading in readings:
                ticker = reading.market_ticker
                if ticker not in prev_by_ticker:
                    prev = _latest_observed_at(session, ticker)
                    prev_by_ticker[ticker] = prev
                    seen.append(ticker)
                    if prev is not None:
                        logger.info(
                            "perp mark poll resuming for {}; last observed_at {} — a "
                            "long silence before the next reading is recorded as a gap",
                            ticker,
                            prev,
                        )
                prev_observed_at = prev_by_ticker[ticker]

                if prev_observed_at is not None and reading.observed_at <= prev_observed_at:
                    result.duplicates_skipped += 1
                    continue

                receipt = round(now_fn())
                available_at = max(
                    reading.available_at if reading.available_at is not None else receipt,
                    reading.observed_at,
                )

                if (
                    prev_observed_at is not None
                    and reading.observed_at - prev_observed_at > gap_threshold
                ):
                    result.gaps_observed += 1
                    logger.warning(
                        "perp mark gap [{}]: {}s between observed_at {} and {} "
                        "(threshold {}s) — recorded as a hole, not filled",
                        ticker,
                        reading.observed_at - prev_observed_at,
                        prev_observed_at,
                        reading.observed_at,
                        gap_threshold,
                    )

                session.add(
                    PerpMarkObservation(
                        market_ticker=ticker,
                        observed_at=reading.observed_at,
                        available_at=available_at,
                        settlement_mark_dollars=reading.settlement_mark,
                        reference_price_dollars=reading.reference_price,
                        liquidation_mark_dollars=reading.liquidation_mark,
                        bid_dollars=reading.bid,
                        ask_dollars=reading.ask,
                        contract_size=reading.contract_size,
                        open_interest=reading.open_interest,
                        leverage_estimate=reading.leverage_estimate,
                        source=source.name,
                        capture_session_id=session_id,
                        source_endpoint=source.name,
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
                prev_by_ticker[ticker] = reading.observed_at

            if pending >= commit_every:
                session.commit()
                pending = 0

            elapsed = now_fn() - tick_start
            remaining = interval_s - elapsed
            if remaining > 0 and now_fn() + remaining < deadline:
                sleep_fn(remaining)
            elif remaining > 0:
                sleep_fn(max(0.0, deadline - now_fn()))
    except KeyboardInterrupt:
        result.stopped_reason = "interrupted"
        logger.info("perp mark poll interrupted by operator")

    session.commit()
    result.tickers_seen = tuple(seen)
    logger.info("perp mark poll finished: {}", result.as_dict())
    return result


__all__ = [
    "CallablePerpMarkSource",
    "MarkPollResult",
    "PerpMarkReadingRaw",
    "PerpMarkSource",
    "poll_perp_marks",
]
