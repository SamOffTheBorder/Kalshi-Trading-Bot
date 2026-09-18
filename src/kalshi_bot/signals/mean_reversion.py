"""Causal BRTI displacement features for a bounded mean-reversion candidate.

This is deliberately a feature, not a claim that crypto mean-reverts.  It
measures the latest usable BRTI observation against a trailing, usable-only
reference window.  The strategy layer decides whether a sufficiently unusual
displacement has incremental value after Kalshi execution costs.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from kalshi_bot.signals.settlement_window import BRTIReading

DEFAULT_MEAN_REVERSION_LOOKBACK_SECONDS = 180
DEFAULT_MEAN_REVERSION_MIN_SAMPLES = 30


@dataclass(frozen=True)
class MeanReversionFeatures:
    """Latest BRTI displacement relative to a causal trailing window."""

    last_value: float | None
    trailing_mean: float | None
    trailing_std: float | None
    displacement: float | None
    zscore: float | None
    sample_count: int


def build_mean_reversion_features(
    readings: Sequence[BRTIReading],
    *,
    now_ts: int,
    lookback_seconds: int = DEFAULT_MEAN_REVERSION_LOOKBACK_SECONDS,
    min_samples: int = DEFAULT_MEAN_REVERSION_MIN_SAMPLES,
) -> MeanReversionFeatures:
    """Build a trailing displacement from readings usable by ``now_ts``.

    The latest reading is intentionally excluded from the trailing reference
    distribution.  That prevents an extreme final observation from diluting
    the very displacement being measured.  A zero-variance window has no
    usable z-score and is returned as unavailable rather than treated as an
    infinitely strong signal.
    """
    if lookback_seconds <= 0:
        raise ValueError("lookback_seconds must be positive")
    if min_samples < 2:
        raise ValueError("min_samples must be at least 2")

    usable = sorted(
        (
            reading
            for reading in readings
            if reading.observed_at <= now_ts and reading.usable_at <= now_ts
        ),
        key=lambda reading: reading.observed_at,
    )
    if not usable:
        return MeanReversionFeatures(None, None, None, None, None, 0)

    latest = usable[-1]
    start_ts = latest.observed_at - lookback_seconds
    trailing = [
        reading.value
        for reading in usable[:-1]
        if start_ts < reading.observed_at <= latest.observed_at
    ]
    if len(trailing) < min_samples:
        return MeanReversionFeatures(latest.value, None, None, None, None, len(trailing))

    mean = sum(trailing) / len(trailing)
    variance = sum((value - mean) ** 2 for value in trailing) / (len(trailing) - 1)
    std = math.sqrt(variance)
    displacement = latest.value - mean
    zscore = displacement / std if std > 0 else None
    return MeanReversionFeatures(latest.value, mean, std, displacement, zscore, len(trailing))


__all__ = [
    "DEFAULT_MEAN_REVERSION_LOOKBACK_SECONDS",
    "DEFAULT_MEAN_REVERSION_MIN_SAMPLES",
    "MeanReversionFeatures",
    "build_mean_reversion_features",
]
