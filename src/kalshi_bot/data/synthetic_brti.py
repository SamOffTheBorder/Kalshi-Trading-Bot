"""Compose a labelled BRTI proxy from constituent-venue USD trade series.

Per design decision D3 (brti-constituent-history): the composer emits a
one-second grid matching BRTI's own publication cadence. For each second it
takes each contributing constituent's last trade price in that second, then
combines across constituents by **median** (not mean or volume-weighted
mean) -- a median resists a single venue's outlier print or stale book,
which is the dominant failure mode in thin hours.

A constituent silent for a second contributes nothing for that second; there
is no forward-fill. `contributor_count == 0` is a gap, not a value, and is
never emitted as a row.

The output carries `provenance="reconstructed_index"` and is never returned
by, or merged into, anything that claims to be captured BRTI (D6 / the
`synthetic-index-reconstruction` spec's "never labelled as the index"
requirement). See `data/brti_index_read.py` for the read-path guard.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from sqlalchemy.orm import Session

from kalshi_bot.data.external_sources import ExternalInstrument
from kalshi_bot.storage.models import ReconstructedIndexObservation

COMPOSER_VERSION = "synthetic-brti-v1"


class CompositionError(ValueError):
    """Raised when a composition input is refused rather than silently
    dropped -- the caller must see why an input did not contribute."""


@dataclass(frozen=True)
class ConstituentTrade:
    """One normalized trade from a constituent venue, the composer's input
    unit. Deliberately narrower than any one venue's own normalized-trade
    dataclass so Kraken and Coinbase trades can feed the same composer."""

    instrument: ExternalInstrument
    observed_at_ms: int
    price: float


@dataclass(frozen=True)
class ReconstructedSecond:
    target_index: str
    observed_at: int  # epoch seconds
    value: float
    contributor_count: int
    contributing_venues: tuple[str, ...]


@dataclass(frozen=True)
class CompositionRefusal:
    venue: str
    reason: str


@dataclass(frozen=True)
class CompositionResult:
    target_index: str
    seconds: tuple[ReconstructedSecond, ...]
    refusals: tuple[CompositionRefusal, ...]
    gap_seconds: tuple[int, ...]
    """Seconds in [start_ts, end_ts) with contributor_count == 0. Recorded
    for coverage reporting; never emitted as a ReconstructedSecond row."""


def _validate_inputs(
    trades_by_venue: dict[str, tuple[ConstituentTrade, ...]],
    *,
    target_index: str,
    target_quote_currency: str,
) -> tuple[dict[str, tuple[ConstituentTrade, ...]], tuple[CompositionRefusal, ...]]:
    accepted: dict[str, tuple[ConstituentTrade, ...]] = {}
    refusals: list[CompositionRefusal] = []
    for venue, trades in trades_by_venue.items():
        if not trades:
            continue
        instrument = trades[0].instrument
        reasons: list[str] = []
        if instrument.source_role != "constituent" or instrument.target_index != target_index:
            reasons.append("non-constituent role")
        if instrument.quote_currency != target_quote_currency:
            reasons.append("quote_currency_mismatch")
        if reasons:
            refusals.append(CompositionRefusal(venue=venue, reason="; ".join(reasons)))
            continue
        accepted[venue] = trades
    return accepted, tuple(refusals)


def compose_synthetic_brti(
    trades_by_venue: dict[str, tuple[ConstituentTrade, ...]],
    *,
    target_index: str = "BRTI",
    target_quote_currency: str = "USD",
    start_ts: int,
    end_ts: int,
) -> CompositionResult:
    """Compose a one-second reconstructed series over ``[start_ts, end_ts)``.

    Refuses (rather than silently drops) any venue whose instrument is not
    `constituent`-roled against ``target_index`` or whose quote currency
    does not match. Accepted venues' trades are then combined per second by
    per-venue-last-price -> cross-venue median.
    """
    if start_ts >= end_ts:
        raise CompositionError("start_ts must precede end_ts")

    accepted, refusals = _validate_inputs(
        trades_by_venue, target_index=target_index, target_quote_currency=target_quote_currency
    )

    # (price, observed_at_ms) of the latest trade per (venue, second), so an
    # out-of-order trade stream still yields each second's true last price.
    last_by_second: dict[int, dict[str, tuple[float, int]]] = defaultdict(dict)
    for venue, trades in accepted.items():
        for trade in trades:
            second = trade.observed_at_ms // 1_000
            if not start_ts <= second < end_ts:
                continue
            current = last_by_second[second].get(venue)
            if current is None or trade.observed_at_ms >= current[1]:
                last_by_second[second][venue] = (trade.price, trade.observed_at_ms)

    seconds: list[ReconstructedSecond] = []
    gap_seconds: list[int] = []
    for second in range(start_ts, end_ts):
        per_venue = {
            venue: price for venue, (price, _ts) in last_by_second.get(second, {}).items()
        }
        if not per_venue:
            gap_seconds.append(second)
            continue
        venues = tuple(sorted(per_venue))
        seconds.append(
            ReconstructedSecond(
                target_index=target_index,
                observed_at=second,
                value=median(per_venue.values()),
                contributor_count=len(per_venue),
                contributing_venues=venues,
            )
        )

    return CompositionResult(
        target_index=target_index,
        seconds=tuple(seconds),
        refusals=refusals,
        gap_seconds=tuple(gap_seconds),
    )


def _format_value(value: float) -> str:
    if value >= 1000:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{value:.10f}".rstrip("0").rstrip(".")


def persist_reconstructed_seconds(
    session: Session,
    result: CompositionResult,
    *,
    composed_at: int,
    composer_version: str = COMPOSER_VERSION,
) -> int:
    """Persist a composition's seconds into `reconstructed_index_observations`.

    Distinct table from `brti_observations` by construction (D6 / the
    "never labelled as the index" requirement) -- this function never writes
    to, and never even imports, the captured-BRTI model. Idempotent per
    `(target_index, observed_at)`: re-running a composition over the same
    window updates existing rows rather than duplicating them.
    """
    written = 0
    for second in result.seconds:
        existing = (
            session.query(ReconstructedIndexObservation)
            .filter_by(target_index=second.target_index, observed_at=second.observed_at)
            .one_or_none()
        )
        if existing is not None:
            existing.value_dollars = _format_value(second.value)
            existing.contributor_count = second.contributor_count
            existing.contributing_venues = list(second.contributing_venues)
            existing.composed_at = composed_at
            existing.composer_version = composer_version
            continue
        session.add(
            ReconstructedIndexObservation(
                target_index=second.target_index,
                observed_at=second.observed_at,
                value_dollars=_format_value(second.value),
                contributor_count=second.contributor_count,
                contributing_venues=list(second.contributing_venues),
                provenance="reconstructed_index",
                composed_at=composed_at,
                composer_version=composer_version,
            )
        )
        written += 1
    session.flush()
    return written


__all__ = [
    "COMPOSER_VERSION",
    "CompositionError",
    "CompositionRefusal",
    "CompositionResult",
    "ConstituentTrade",
    "ReconstructedSecond",
    "compose_synthetic_brti",
    "persist_reconstructed_seconds",
]
