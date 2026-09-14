"""Foreground poll of Kalshi public trades, with causal timestamps and
honest gap accounting -- the trade-stream analogue of ``brti.poll.poll_brti``
and ``l2.poll.poll_l2``.

Unlike an order book (one state snapshot per tick) or BRTI (one index level
per tick), Kalshi's ``GET /markets/trades`` is a paginated stream of
discrete, already-timestamped, uniquely-identified events. So this loop is
closer in shape to a resumable backfill than a state poll: each tick it
pulls every trade with ``created_time`` after the last one already stored
for that ticker, following the response cursor to page through however many
landed since the previous tick, and stops --- it never keeps paginating
into old history once caught up.

Contract, identical in spirit to the other capture loops:

1. **Causal timestamps** -- ``observed_at`` is the trade's own
   ``created_time`` (an exchange-assigned instant, more causal than local
   receipt); ``available_at`` is local receipt time, never earlier.
2. **Gaps recorded, never filled** -- a stall between consecutive trades
   above the expected spacing is logged, not backfilled with a fabricated
   trade.
3. **Resumable** -- on start, the latest ``observed_at`` already stored per
   ticker is read back, so a stop/restart shows as a gap rather than being
   silently skipped or re-fetched from scratch.
4. **Foreground only** -- runs until ``duration_s`` elapses or the operator
   interrupts (``KeyboardInterrupt`` -> clean ``TradePollResult``). It never
   spawns a thread, schedules a task, or restarts itself.

Read-only: the public, unauthenticated ``/markets/trades`` GET.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import PublicTrade


@dataclass(frozen=True)
class TradeReadingRaw:
    """One public trade straight from a source, before persistence.

    ``observed_at`` is epoch seconds the trade executed (the exchange's own
    timestamp). ``price_dollars`` / ``quantity_fp`` are kept as Kalshi's
    fixed-point dollar strings. ``trade_id`` is the exchange's own id --
    already unique, unlike Kraken's CSV export, so no synthetic id is
    needed. ``available_at`` is ``None`` when the source cannot distinguish
    it from receipt; the loop then stamps local receipt time.
    """

    market_ticker: str
    trade_id: str
    observed_at: int
    price_dollars: str
    quantity_fp: str
    taker_side: str | None = None
    available_at: int | None = None
    extra: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class TradeSource(Protocol):
    """A pollable trade origin. ``fetch(since_by_ticker)`` returns every new
    trade observed after each ticker's last-seen ``observed_at`` (or all
    available history for a ticker not yet in the map), across whatever
    tickers the source currently covers. An empty list is a skipped tick,
    not an error."""

    name: str

    def fetch(self, since_by_ticker: dict[str, int | None]) -> Sequence[TradeReadingRaw]: ...


class CallableTradeSource:
    """Adapts a ``(dict[str, int | None]) -> Sequence[TradeReadingRaw]``
    callable to ``TradeSource`` -- for tests and lightweight wiring."""

    def __init__(
        self,
        fn: Callable[[dict[str, int | None]], Sequence[TradeReadingRaw]],
        *,
        name: str,
    ) -> None:
        self._fn = fn
        self.name = name

    def fetch(self, since_by_ticker: dict[str, int | None]) -> Sequence[TradeReadingRaw]:
        return self._fn(since_by_ticker)


@dataclass
class TradePollResult:
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
        select(func.max(PublicTrade.observed_at)).where(PublicTrade.market_ticker == ticker)
    )


def _existing_trade_ids(session: Session, ticker: str, *, since: int | None) -> set[str]:
    """Trade ids already stored for ``ticker`` at or after ``since`` -- used
    to dedupe a source's response against what this tick already persisted
    (a source may legitimately return a trade whose ``observed_at`` ties the
    last-seen one, since multiple trades can share a timestamp)."""
    if since is None:
        return set()
    stmt = select(PublicTrade.trade_id).where(
        PublicTrade.market_ticker == ticker, PublicTrade.observed_at >= since
    )
    return {row for row in session.scalars(stmt) if row is not None}


def poll_public_trades(
    session: Session,
    source: TradeSource,
    *,
    interval_s: float,
    duration_s: float,
    session_id: str,
    expected_gap_s: float | None = None,
    now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
    commit_every: int = 30,
) -> TradePollResult:
    """Poll ``source`` every ``interval_s`` seconds for up to ``duration_s``
    seconds, persisting each new trade as a ``PublicTrade``.

    Dedup and gap accounting are per ticker: a stall on one market is that
    market's gap, and resuming reads each ticker's own latest
    ``observed_at``. A trade whose id is already stored for that ticker at
    or after its ``observed_at`` is skipped as a duplicate.

    ``expected_gap_s`` (default ``2.5 * interval_s``) is the spacing above
    which a jump between two consecutive trades for one ticker is logged as
    a gap. A quiet market with no trades is not itself a gap -- only a jump
    larger than the threshold is recorded as one.
    """
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    gap_threshold = expected_gap_s if expected_gap_s is not None else interval_s * 2.5

    result = TradePollResult()
    prev_by_ticker: dict[str, int | None] = {}
    known_ids_by_ticker: dict[str, set[str]] = {}
    seen: list[str] = []

    start = now_fn()
    deadline = start + duration_s
    pending = 0
    try:
        while now_fn() < deadline:
            tick_start = now_fn()
            result.polls += 1
            since_by_ticker = dict(prev_by_ticker)
            try:
                readings = list(source.fetch(since_by_ticker))
            except Exception as exc:  # a transient source failure is a skipped tick
                result.errors += 1
                logger.warning("trade source {} raised: {}", source.name, exc)
                readings = []

            if not readings:
                result.empty_ticks += 1
            for reading in sorted(readings, key=lambda r: (r.market_ticker, r.observed_at)):
                ticker = reading.market_ticker
                if ticker not in prev_by_ticker:
                    prev = _latest_observed_at(session, ticker)
                    prev_by_ticker[ticker] = prev
                    known_ids_by_ticker[ticker] = _existing_trade_ids(session, ticker, since=prev)
                    seen.append(ticker)
                    if prev is not None:
                        logger.info(
                            "trade poll resuming for {}; last observed_at {} — a long "
                            "silence before the next trade is recorded as a gap",
                            ticker,
                            prev,
                        )
                prev_observed_at = prev_by_ticker[ticker]
                known_ids = known_ids_by_ticker.setdefault(ticker, set())

                if prev_observed_at is not None and reading.observed_at < prev_observed_at:
                    result.duplicates_skipped += 1
                    continue
                if reading.trade_id in known_ids:
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
                        "trade gap [{}]: {}s between observed_at {} and {} "
                        "(threshold {}s) — recorded as a hole, not filled",
                        ticker,
                        reading.observed_at - prev_observed_at,
                        prev_observed_at,
                        reading.observed_at,
                        gap_threshold,
                    )

                session.add(
                    PublicTrade(
                        market_ticker=ticker,
                        observed_at=reading.observed_at,
                        available_at=available_at,
                        price_dollars=reading.price_dollars,
                        quantity_fp=reading.quantity_fp,
                        taker_side=reading.taker_side,
                        trade_id=reading.trade_id,
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
                known_ids.add(reading.trade_id)

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
        logger.info("trade poll interrupted by operator")

    session.commit()
    result.tickers_seen = tuple(seen)
    logger.info("trade poll finished: {}", result.as_dict())
    return result


__all__ = [
    "CallableTradeSource",
    "TradePollResult",
    "TradeReadingRaw",
    "TradeSource",
    "poll_public_trades",
]
