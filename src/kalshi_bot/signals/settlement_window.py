"""KXBTC15M settlement-window features and a settlement-probability model
(kxbtc15m-validation-rebuild §4.1, design decision "Prioritize settlement-
aware probability").

KXBTC15M asks "is BTC up over this 15-minute window?" and resolves from the
published methodology (`signals.fees.ResolutionSpec`, version
`2026-09-kxbtc15m-brti-60s`):

    YES  iff  mean(BRTI over the 60 s ending at close_ts)
              >=  mean(BRTI over the 60 s ending at open_ts)
    ties -> YES

So the contract is a bet on the sign of

    Δ = close_window_avg - open_window_avg

The *open* window average is FIXED the moment the window opens — by any
decision time `now_ts` inside `[open_ts, close_ts]` it is a known constant,
the reference level. What is uncertain is the *close* window average, which
depends on BRTI's path over the remaining `close_ts - now_ts` seconds plus
the 60 s averaging at the end.

This module is deliberately storage-free and strategy-free (same split as
`strategy/levels.py`): it takes plain timestamped BRTI readings in and
returns features / a probability out, so it is unit-testable with synthetic
series and has no ORM or protocol dependency. The strategy layer
(`strategy/settlement_prob.py`, §4.2/§4.3) assembles the readings, calls
this, compares the probability to executable prices net of friction, and
decides.

**Causal discipline:** every function here takes only observations at or
before `now_ts`. A BRTI reading is usable when its `available_at <= now_ts`
(the data-contract layer, §1.3, stamps that). The caller is responsible for
passing an already-filtered series; `window_average` additionally guards the
right edge.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from scipy.stats import norm

DEFAULT_WINDOW_SECONDS = 60
"""The BRTI averaging window at each of open and close — `ResolutionSpec.
window_seconds`. Kept as a module default so callers that don't thread a
ResolutionSpec through still match the published rule."""


@dataclass(frozen=True)
class BRTIReading:
    """One timestamped BRTI index value. `available_at` is when a live
    system could first have acted on it (§1.3); `observed_at` is the
    instant the value refers to. For historical CF Benchmarks data the two
    are typically equal; for a delayed feed they differ and the caller
    filters on `available_at`."""

    observed_at: int  # epoch seconds the value refers to
    value: float  # BRTI in USD
    available_at: int | None = None  # epoch seconds the value could first be used

    @property
    def usable_at(self) -> int:
        return self.available_at if self.available_at is not None else self.observed_at


@dataclass(frozen=True)
class SettlementWindowFeatures:
    """Everything the settlement-probability model needs for one KXBTC15M
    window at one decision time. All fields are computable from BRTI
    readings at or before `now_ts` plus the window's own open/close times."""

    now_ts: int
    open_ts: int
    close_ts: int

    reference_avg: float | None
    """60 s BRTI average ending at `open_ts` — the level the close average
    must beat for YES. None when the open window is not covered by the
    supplied readings (the caller should then HOLD, not guess)."""

    current_avg: float | None
    """60 s BRTI average ending at the latest reading at/<= now_ts — the
    running estimate of where the close average sits right now."""

    last_value: float | None  # the single most recent BRTI reading <= now_ts
    seconds_remaining: int  # close_ts - now_ts, floored at 0
    fraction_elapsed: float  # (now_ts - open_ts) / (close_ts - open_ts), clamped [0, 1]

    drift_so_far: float | None
    """current_avg - reference_avg: how far the window has moved already.
    Positive favours YES. None if either average is missing."""

    realized_vol_per_sec: float | None
    """Standard deviation of 1-second-scaled BRTI log returns over the
    readings so far this window (or the caller's lookback). Used to scale
    the remaining-time uncertainty. None with < 3 readings."""


def window_average(
    readings: Sequence[BRTIReading],
    end_ts: int,
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    now_ts: int | None = None,
) -> float | None:
    """Mean BRTI value over `(end_ts - window_seconds, end_ts]`.

    Returns None if no reading falls in that interval. When `now_ts` is
    given, readings usable only after `now_ts` are excluded first — so a
    caller can ask for the *close* window average using whatever is known
    so far (it will usually be None until the window is nearly over, which
    is the correct signal to the strategy that the outcome is still open).
    """
    lo = end_ts - window_seconds
    vals = [
        r.value
        for r in readings
        if lo < r.observed_at <= end_ts and (now_ts is None or r.usable_at <= now_ts)
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _realized_vol_per_sec(readings: Sequence[BRTIReading], now_ts: int) -> float | None:
    usable = sorted(
        (r for r in readings if r.usable_at <= now_ts and r.value > 0),
        key=lambda r: r.observed_at,
    )
    if len(usable) < 3:
        return None
    per_sec_returns: list[float] = []
    for a, b in pairwise(usable):
        dt = b.observed_at - a.observed_at
        if dt <= 0:
            continue
        # log return scaled to a 1-second step (variance scales with time)
        per_sec_returns.append(math.log(b.value / a.value) / math.sqrt(dt))
    if len(per_sec_returns) < 2:
        return None
    mean = sum(per_sec_returns) / len(per_sec_returns)
    var = sum((x - mean) ** 2 for x in per_sec_returns) / (len(per_sec_returns) - 1)
    return math.sqrt(var)


def build_features(
    readings: Sequence[BRTIReading],
    *,
    now_ts: int,
    open_ts: int,
    close_ts: int,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> SettlementWindowFeatures:
    """Assemble `SettlementWindowFeatures` for one window at one decision
    time. Only readings usable at/<= `now_ts` are consulted."""
    if not open_ts < close_ts:
        raise ValueError("require open_ts < close_ts")

    usable = [r for r in readings if r.usable_at <= now_ts]
    usable.sort(key=lambda r: r.observed_at)

    reference_avg = window_average(usable, open_ts, window_seconds=window_seconds, now_ts=now_ts)

    # "current" close-average proxy: the 60 s ending at the latest reading we have.
    current_avg: float | None = None
    last_value: float | None = None
    if usable:
        last = usable[-1]
        last_value = last.value
        current_avg = window_average(
            usable, last.observed_at, window_seconds=window_seconds, now_ts=now_ts
        )

    seconds_remaining = max(0, close_ts - now_ts)
    span = close_ts - open_ts
    fraction_elapsed = min(1.0, max(0.0, (now_ts - open_ts) / span))

    drift_so_far = (
        current_avg - reference_avg
        if (current_avg is not None and reference_avg is not None)
        else None
    )

    return SettlementWindowFeatures(
        now_ts=now_ts,
        open_ts=open_ts,
        close_ts=close_ts,
        reference_avg=reference_avg,
        current_avg=current_avg,
        last_value=last_value,
        seconds_remaining=seconds_remaining,
        fraction_elapsed=fraction_elapsed,
        drift_so_far=drift_so_far,
        realized_vol_per_sec=_realized_vol_per_sec(usable, now_ts),
    )


def settlement_probability(
    features: SettlementWindowFeatures,
    *,
    vol_per_sec: float | None = None,
    drift_per_sec: float = 0.0,
) -> float | None:
    """P(this KXBTC15M window resolves YES), i.e. P(Δ >= 0), from features.

    Model (a Brownian bridge-style approximation, deliberately simple — it
    is the BASELINE the walk-forward report calibrates and that trend
    features must beat, design decision "treat trend as conditional
    evidence"):

    - The close 60 s average ≈ the current level plus the BRTI move over the
      remaining `seconds_remaining`, whose std is
      `sigma_1s * sqrt(seconds_remaining)`.
    - Δ ≈ drift_so_far + (that move) + drift_per_sec * seconds_remaining.
    - P(Δ >= 0) = Phi( (drift_so_far + drift_per_sec * T) / (sigma_1s *
      sqrt(T)) ), with the tie-goes-to-YES rule already satisfied by the
      >= boundary.

    Returns None when the inputs to even this baseline are missing
    (`drift_so_far` unknown, or no volatility estimate available) — the
    strategy must HOLD, not substitute a guess. When `seconds_remaining`
    is 0 the outcome is (almost) determined: return 1.0 if `drift_so_far
    >= 0` else 0.0.
    """
    if features.drift_so_far is None:
        return None

    if features.seconds_remaining <= 0:
        return 1.0 if features.drift_so_far >= 0.0 else 0.0

    sigma_1s = vol_per_sec if vol_per_sec is not None else features.realized_vol_per_sec
    if sigma_1s is None or sigma_1s <= 0:
        return None

    # sigma_1s is in log-return units; convert the remaining-move std to
    # price units at the current level.
    level = features.current_avg or features.last_value
    if not level or level <= 0:
        return None

    t = float(features.seconds_remaining)
    price_std = level * sigma_1s * math.sqrt(t)
    expected_delta = features.drift_so_far + drift_per_sec * t
    z = expected_delta / price_std
    return float(norm.cdf(z))


__all__ = [
    "DEFAULT_WINDOW_SECONDS",
    "BRTIReading",
    "SettlementWindowFeatures",
    "build_features",
    "settlement_probability",
    "window_average",
]
