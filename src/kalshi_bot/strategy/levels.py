"""Deterministic price-level detection shared by the v2 trend strategies
(tasks.md 6.1/6.2, design D2).

Design D2's level definition, verbatim: "swing highs/lows over a lookback
window, confirmed by N touches within a tolerance band, plus session VWAP.
A level is 'respected' when price approaches within the band and reverses
without closing through." This module is the one place that definition is
implemented — `trend_scalp.py` and `level_break.py` both consume it rather
than each re-deriving levels their own way, so "is this a level" always
means the same thing across strategies.

Deliberately has no notion of stops, targets, R, or entries — it only
answers "where are the levels, and has price respected or broken this one,"
in plain float price terms (BTC spot USD), independent of contract pricing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SpotBar:
    """One OHLCV bar of the underlying's spot price — deliberately decoupled
    from `storage.models.SpotCandle` (a SQLAlchemy row) so this module has
    zero storage/ORM dependency and is trivially unit-testable with plain
    synthetic data."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class SwingLevel:
    price: float
    kind: Literal["high", "low"]
    touches: int
    first_touch_ts: int
    last_touch_ts: int


def compute_vwap(bars: list[SpotBar]) -> float | None:
    """Volume-weighted average price over `bars`. None if there's no volume
    to weight by (e.g. a venue that doesn't report it) — callers should
    treat that as "VWAP unavailable," not "VWAP is the simple average.\""""
    total_volume = sum(b.volume for b in bars)
    if total_volume <= 0:
        return None
    return sum(b.close * b.volume for b in bars) / total_volume


def find_swing_levels(
    bars: list[SpotBar],
    *,
    lookback: int,
    tolerance_pct: float,
    min_touches: int = 2,
) -> list[SwingLevel]:
    """Deterministic swing-high/low detection: a bar is a local swing high
    (low) when its high (low) is the maximum (minimum) within a symmetric
    `lookback`-bar window centered on it. Swing points within
    `tolerance_pct` of each other are merged into one level; a level is
    reported only once it has been touched at least `min_touches` times
    (design D2: "confirmed by N touches").

    No discretion anywhere in this function — same `bars` in always
    produces the same levels out, which is the whole point of D2's
    "deterministic, no discretion" requirement.
    """
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    if not 0.0 < tolerance_pct < 1.0:
        raise ValueError("tolerance_pct must be in (0, 1)")
    if min_touches < 1:
        raise ValueError("min_touches must be >= 1")

    raw_highs: list[tuple[int, float]] = []
    raw_lows: list[tuple[int, float]] = []
    n = len(bars)
    for i in range(n):
        lo = max(0, i - lookback)
        hi = min(n, i + lookback + 1)
        window = bars[lo:hi]
        if bars[i].high == max(b.high for b in window):
            raw_highs.append((bars[i].ts, bars[i].high))
        if bars[i].low == min(b.low for b in window):
            raw_lows.append((bars[i].ts, bars[i].low))

    return _merge_touches(raw_highs, "high", tolerance_pct, min_touches) + _merge_touches(
        raw_lows, "low", tolerance_pct, min_touches
    )


def _merge_touches(
    points: list[tuple[int, float]],
    kind: Literal["high", "low"],
    tolerance_pct: float,
    min_touches: int,
) -> list[SwingLevel]:
    if not points:
        return []
    # Process in price order so nearby swing points merge deterministically
    # regardless of the timestamp order they were discovered in.
    ordered = sorted(points, key=lambda p: p[1])
    levels: list[SwingLevel | None] = []
    cluster: list[tuple[int, float]] = [ordered[0]]
    for ts, price in ordered[1:]:
        cluster_price = cluster[0][1]
        if abs(price - cluster_price) / cluster_price <= tolerance_pct:
            cluster.append((ts, price))
        else:
            levels.append(_level_from_cluster(cluster, kind, min_touches))
            cluster = [(ts, price)]
    levels.append(_level_from_cluster(cluster, kind, min_touches))
    return [lvl for lvl in levels if lvl is not None]


def _level_from_cluster(
    cluster: list[tuple[int, float]], kind: Literal["high", "low"], min_touches: int
) -> SwingLevel | None:
    if len(cluster) < min_touches:
        return None
    avg_price = sum(p for _ts, p in cluster) / len(cluster)
    timestamps = [ts for ts, _p in cluster]
    return SwingLevel(
        price=avg_price,
        kind=kind,
        touches=len(cluster),
        first_touch_ts=min(timestamps),
        last_touch_ts=max(timestamps),
    )


def spot_r_to_contract_cents(
    entry_price: float,
    stop_or_target_price: float,
    entry_price_cents: int,
    *,
    side: Literal["yes", "no"],
) -> int:
    """Convert a spot-terms distance (entry to stop, or entry to target)
    into a contract-cents distance from `entry_price_cents`, by carrying the
    FRACTIONAL distance across unchanged: `pct = (spot_level - entry) /
    entry`, then `cents_level = entry_price_cents +/- round(pct *
    entry_price_cents)`.

    `side` matters for the sign: a YES contract's price moves WITH spot (spot
    up -> YES price up), but a NO contract's price moves AGAINST spot (spot
    up -> NO price down, since NO price = 100 - yes_price) — so the same
    upward spot move that is a bullish target for a YES position is a
    bearish stop-out direction for a NO position's own contract price, and
    vice versa. This flips the sign of the cents delta for `side="no"` so
    "moving toward the target" always means "cents delta in the strategy's
    favor," regardless of which side was bought.

    This is deliberately NOT a Black-Scholes inversion — see `base.Decision`'s
    docstring on `stop_price_cents`/`target_price_cents` for why: KXBTC15M is
    a single-strike binary, not a continuously spot-tracking instrument, and
    inverting a pricing model just to build an exit trigger would reintroduce
    the zero-drift assumption design D2 moved away from. This is a simple,
    deterministic proportional carry-across instead — a stop 1% away from
    entry in spot terms becomes a contract-price move of 1% of the entry
    price in cents, clamped to stay within [1, 99].
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    pct = (stop_or_target_price - entry_price) / entry_price
    if side == "no":
        pct = -pct
    delta_cents = round(pct * entry_price_cents)
    return max(1, min(99, entry_price_cents + delta_cents))


def level_is_respected(
    level: SwingLevel, approach_price: float, close_price: float, tolerance_pct: float
) -> bool:
    """True when price approached within `tolerance_pct` of `level` and the
    bar CLOSED without breaking through it (design D2: "reverses without
    closing through"). Direction-aware: a support (low) is broken by
    closing below it; resistance (high) is broken by closing above it."""
    within_band = abs(approach_price - level.price) / level.price <= tolerance_pct
    if not within_band:
        return False
    if level.kind == "low":
        return close_price >= level.price
    return close_price <= level.price


__all__ = [
    "SpotBar",
    "SwingLevel",
    "compute_vwap",
    "find_swing_levels",
    "level_is_respected",
    "spot_r_to_contract_cents",
]
