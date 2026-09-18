"""Foreground poll of Kalshi L2 order-book snapshots, with causal timestamps
and honest gap accounting -- the per-market analogue of
``perps.mark_poll.poll_perp_marks`` (itself modeled on ``brti.poll.poll_brti``).

Kalshi's ``GET /markets/{ticker}/orderbook`` returns a full-depth snapshot
with no timestamp of its own, so ``observed_at`` is local receipt time --
the same "source cannot distinguish observed_at from available_at" case the
BRTI and perp-mark loops already handle by stamping both to receipt.

Contract, identical in spirit to the BRTI and perp-mark loops:

1. **Causal timestamps** -- ``observed_at`` and ``available_at`` are both the
   local receipt instant (Kalshi's orderbook response carries no exchange
   timestamp to be more causal than that).
2. **Gaps recorded, never filled.**
3. **Resumable** -- on start, the latest ``observed_at`` already stored per
   ticker is read back, so a stop/restart shows as a gap.
4. **Foreground only** -- runs until ``duration_s`` elapses or the operator
   interrupts (``KeyboardInterrupt`` -> clean ``L2PollResult``). It never
   spawns a thread, schedules a task, or restarts itself.

Read-only: the public, unauthenticated ``/markets/*/orderbook`` GET.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import OrderBookSnapshot


@dataclass(frozen=True)
class L2ReadingRaw:
    """One order-book snapshot straight from a source, before persistence.

    ``bids`` / ``asks`` are kept as the raw ``[price_str, size_str]`` pair
    lists Kalshi returns (dollar-denominated YES-side prices) -- this module
    does not reinterpret depth, it only timestamps and persists it.
    ``observed_at`` / ``available_at`` are epoch seconds; when the source
    cannot distinguish them (Kalshi's orderbook has no server timestamp)
    pass ``None`` for ``available_at`` and the loop stamps local receipt
    time for both.
    """

    market_ticker: str
    bids: list[list[str]]
    asks: list[list[str]]
    observed_at: int | None = None
    available_at: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class L2Source(Protocol):
    """A pollable L2 origin. ``fetch()`` returns the latest snapshot for
    every ticker it covers (or an empty list when briefly unavailable -- the
    loop treats that as a skipped tick, not an error)."""

    name: str

    def fetch(self) -> Sequence[L2ReadingRaw]: ...


class CallableL2Source:
    """Adapts a ``() -> Sequence[L2ReadingRaw]`` callable to ``L2Source`` --
    for tests and lightweight wiring."""

    def __init__(self, fn: Callable[[], Sequence[L2ReadingRaw]], *, name: str) -> None:
        self._fn = fn
        self.name = name

    def fetch(self) -> Sequence[L2ReadingRaw]:
        return self._fn()


@dataclass
class L2PollResult:
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
        select(func.max(OrderBookSnapshot.observed_at)).where(
            OrderBookSnapshot.market_ticker == ticker
        )
    )


def poll_l2(
    session: Session,
    source: L2Source,
    *,
    interval_s: float,
    duration_s: float,
    session_id: str,
    expected_gap_s: float | None = None,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    commit_every: int = 30,
) -> L2PollResult:
    """Poll ``source`` every ``interval_s`` seconds for up to ``duration_s``
    seconds, persisting each new per-ticker snapshot as an
    ``OrderBookSnapshot``.

    Dedup and gap accounting are per ticker: a stall on one market is that
    market's gap, and resuming reads each ticker's own latest
    ``observed_at``. A snapshot whose ``observed_at`` is <= the last stored
    one for that ticker is skipped as a duplicate tick.

    ``expected_gap_s`` (default ``2.5 * interval_s``) is the spacing above
    which a jump between consecutive ``observed_at`` values for one ticker is
    logged as a gap. Gaps are only recorded, never backfilled.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    gap_threshold = expected_gap_s if expected_gap_s is not None else interval_s * 2.5

    result = L2PollResult()
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
                logger.warning("l2 source {} raised: {}", source.name, exc)
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
                            "l2 poll resuming for {}; last observed_at {} — a long "
                            "silence before the next reading is recorded as a gap",
                            ticker,
                            prev,
                        )
                prev_observed_at = prev_by_ticker[ticker]

                receipt = round(now_fn())
                observed_at = reading.observed_at if reading.observed_at is not None else receipt
                available_at = max(
                    reading.available_at if reading.available_at is not None else receipt,
                    observed_at,
                )

                if prev_observed_at is not None and observed_at <= prev_observed_at:
                    result.duplicates_skipped += 1
                    continue

                if (
                    prev_observed_at is not None
                    and observed_at - prev_observed_at > gap_threshold
                ):
                    result.gaps_observed += 1
                    logger.warning(
                        "l2 gap [{}]: {}s between observed_at {} and {} "
                        "(threshold {}s) — recorded as a hole, not filled",
                        ticker,
                        observed_at - prev_observed_at,
                        prev_observed_at,
                        observed_at,
                        gap_threshold,
                    )

                session.add(
                    OrderBookSnapshot(
                        market_ticker=ticker,
                        observed_at=observed_at,
                        available_at=available_at,
                        bids=reading.bids,
                        asks=reading.asks,
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
                result.first_observed_at = result.first_observed_at or observed_at
                result.last_observed_at = observed_at
                prev_by_ticker[ticker] = observed_at

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
        logger.info("l2 poll interrupted by operator")

    session.commit()
    result.tickers_seen = tuple(seen)
    logger.info("l2 poll finished: {}", result.as_dict())
    return result


__all__ = [
    "CallableL2Source",
    "L2PollResult",
    "L2ReadingRaw",
    "L2Source",
    "poll_l2",
]
