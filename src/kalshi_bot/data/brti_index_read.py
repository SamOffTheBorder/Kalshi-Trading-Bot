"""The captured-BRTI read path's provenance guard.

`synthetic-index-reconstruction` spec, "Reconstructed output is never
labelled as the index": a consumer requesting captured index data over a
window covered only by reconstruction SHALL receive an empty or
insufficient-data result rather than reconstructed values. This module is
that read path's single entry point -- it queries only `BRTIObservation`
and has no import of, or fallback to, `ReconstructedIndexObservation`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import BRTIObservation


@dataclass(frozen=True)
class CapturedBRTIReading:
    observed_at: int
    available_at: int
    value: float
    source: str


@dataclass(frozen=True)
class CapturedBRTIResult:
    readings: tuple[CapturedBRTIReading, ...]
    sufficient: bool
    reason: str


def read_captured_brti(
    session: Session, *, start_ts: int, end_ts: int, min_readings: int = 1
) -> CapturedBRTIResult:
    """Return captured BRTI readings in ``[start_ts, end_ts)``, or an
    explicit insufficient-data result. Never substitutes reconstructed
    values -- there is no code path here that can reach them."""

    if start_ts >= end_ts:
        raise ValueError("start_ts must precede end_ts")
    rows = session.scalars(
        select(BRTIObservation)
        .where(BRTIObservation.observed_at >= start_ts, BRTIObservation.observed_at < end_ts)
        .order_by(BRTIObservation.observed_at)
    ).all()
    readings = tuple(
        CapturedBRTIReading(
            observed_at=row.observed_at,
            available_at=row.available_at,
            value=float(row.value_dollars),
            source=row.source,
        )
        for row in rows
    )
    if len(readings) < min_readings:
        return CapturedBRTIResult(
            readings=(), sufficient=False, reason="insufficient_captured_data"
        )
    return CapturedBRTIResult(readings=readings, sufficient=True, reason="ok")


__all__ = ["CapturedBRTIReading", "CapturedBRTIResult", "read_captured_brti"]
