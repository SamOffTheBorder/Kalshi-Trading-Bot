"""Short-horizon trend / pullback features on BRTI data
(kxbtc15m-validation-rebuild §4.4, design decision "treat trend as
conditional evidence").

design.md is explicit: a trend signal "cannot trade merely because
direction is positive; it must improve out-of-sample net value after
execution costs" over the settlement-aware baseline (`signals/
settlement_window.py`). So this module deliberately does NOT emit a trade
decision. It produces a small set of causally-computed features from BRTI
readings that a strategy variant can feed to the baseline model as a drift
estimate, or gate on — and §4.6's walk-forward report is what judges
whether adding them earns their keep.

Everything here consumes only readings at or before `now_ts` (via
`BRTIReading.usable_at`), same discipline as `settlement_window`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from kalshi_bot.signals.settlement_window import BRTIReading

DEFAULT_TREND_LOOKBACK_SECONDS = 180
DEFAULT_PULLBACK_LOOKBACK_SECONDS = 300


@dataclass(frozen=True)
class ShortHorizonTrendFeatures:
    """Causally-computed short-horizon BRTI trend features at one decision
    time. All optional-typed fields are None when there is not enough usable
    history to compute them honestly (the caller then simply does not use
    that feature — it never substitutes a zero)."""

    now_ts: int
    lookback_seconds: int

    slope_per_sec: float | None
    """OLS slope of BRTI value vs. time over the lookback window, in
    USD/second. Positive = rising. This is the natural `drift_per_sec`
    estimate to hand the settlement-aware baseline model."""

    return_over_lookback: float | None
    """log(last / first) over the lookback window — a scale-free trend
    magnitude."""

    trend_z: float | None
    """`return_over_lookback` divided by the window's own realized
    volatility (std of per-second-scaled log returns times sqrt(lookback)) —
    how large the move is relative to noise. |trend_z| small => no real
    trend."""

    pullback_fraction: float | None
    """Over a (usually longer) pullback window: how far BRTI has retraced
    from the window's extreme back toward its start, as a fraction in
    [0, 1] of the extreme-to-start distance. ~0 = at the extreme (trend
    intact), ~1 = fully retraced (trend faded). None if the window never
    moved."""

    pullback_direction: int
    """+1 if the pullback window's extreme was a HIGH (an up-move that may
    be retracing), -1 if a LOW, 0 if flat/unknown. Pairs with
    `pullback_fraction` to say "a X% pullback of an up-move"."""


def _usable_sorted(readings: Sequence[BRTIReading], now_ts: int) -> list[BRTIReading]:
    return sorted(
        (r for r in readings if r.usable_at <= now_ts and r.value > 0),
        key=lambda r: r.observed_at,
    )


def _ols_slope(points: Sequence[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    sx = sum(x for x, _ in points)
    sy = sum(y for _, y in points)
    sxx = sum(x * x for x, _ in points)
    sxy = sum(x * y for x, y in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom


def _realized_vol_over(readings: Sequence[BRTIReading]) -> float | None:
    if len(readings) < 3:
        return None
    per_sec: list[float] = []
    for a, b in pairwise(readings):
        dt = b.observed_at - a.observed_at
        if dt <= 0:
            continue
        per_sec.append(math.log(b.value / a.value) / math.sqrt(dt))
    if len(per_sec) < 2:
        return None
    mean = sum(per_sec) / len(per_sec)
    var = sum((x - mean) ** 2 for x in per_sec) / (len(per_sec) - 1)
    return math.sqrt(var)


def build_trend_features(
    readings: Sequence[BRTIReading],
    *,
    now_ts: int,
    trend_lookback_seconds: int = DEFAULT_TREND_LOOKBACK_SECONDS,
    pullback_lookback_seconds: int = DEFAULT_PULLBACK_LOOKBACK_SECONDS,
) -> ShortHorizonTrendFeatures:
    usable = _usable_sorted(readings, now_ts)

    trend_cut = now_ts - trend_lookback_seconds
    trend_window = [r for r in usable if r.observed_at >= trend_cut]

    slope_per_sec: float | None = None
    return_over_lookback: float | None = None
    trend_z: float | None = None
    if len(trend_window) >= 2:
        t0 = trend_window[0].observed_at
        slope_per_sec = _ols_slope([(r.observed_at - t0, r.value) for r in trend_window])
        first, last = trend_window[0].value, trend_window[-1].value
        if first > 0 and last > 0:
            return_over_lookback = math.log(last / first)
            sigma_1s = _realized_vol_over(trend_window)
            span = trend_window[-1].observed_at - t0
            if sigma_1s and sigma_1s > 0 and span > 0:
                trend_z = return_over_lookback / (sigma_1s * math.sqrt(span))

    pb_cut = now_ts - pullback_lookback_seconds
    pb_window = [r for r in usable if r.observed_at >= pb_cut]
    pullback_fraction: float | None = None
    pullback_direction = 0
    if len(pb_window) >= 3:
        start = pb_window[0].value
        last = pb_window[-1].value
        hi = max(r.value for r in pb_window)
        lo = min(r.value for r in pb_window)
        up_move = hi - start
        down_move = start - lo
        if up_move >= down_move and up_move > 0:
            pullback_direction = 1
            pullback_fraction = _clamp01((hi - last) / up_move)
        elif down_move > 0:
            pullback_direction = -1
            pullback_fraction = _clamp01((last - lo) / down_move)

    return ShortHorizonTrendFeatures(
        now_ts=now_ts,
        lookback_seconds=trend_lookback_seconds,
        slope_per_sec=slope_per_sec,
        return_over_lookback=return_over_lookback,
        trend_z=trend_z,
        pullback_fraction=pullback_fraction,
        pullback_direction=pullback_direction,
    )


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


__all__ = [
    "DEFAULT_PULLBACK_LOOKBACK_SECONDS",
    "DEFAULT_TREND_LOOKBACK_SECONDS",
    "ShortHorizonTrendFeatures",
    "build_trend_features",
]
