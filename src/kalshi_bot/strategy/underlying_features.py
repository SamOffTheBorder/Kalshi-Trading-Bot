"""Causal, asset-isolated features built from normalized external bars."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class UnderlyingBar:
    asset_id: str
    cadence_minutes: int
    open_ts: int
    close_ts: int
    close: float
    available_at: int


@dataclass(frozen=True)
class UnderlyingFeatures:
    asset_id: str
    cadence_minutes: int
    asof_ts: int
    close: float | None
    return_lookback: float | None
    realized_volatility: float | None
    sample_count: int
    available: bool
    reason: str


def build_underlying_features(
    bars: Iterable[UnderlyingBar],
    *,
    asset_id: str,
    cadence_minutes: int,
    decision_ts: int,
    lookback_bars: int = 20,
) -> UnderlyingFeatures:
    if lookback_bars < 1:
        raise ValueError("lookback_bars must be positive")
    usable = sorted(
        (
            bar
            for bar in bars
            if bar.asset_id == asset_id
            and bar.cadence_minutes == cadence_minutes
            and bar.close_ts <= decision_ts
            and bar.available_at <= decision_ts
        ),
        key=lambda bar: bar.close_ts,
    )
    if len(usable) < lookback_bars + 1:
        return UnderlyingFeatures(
            asset_id,
            cadence_minutes,
            decision_ts,
            None,
            None,
            None,
            len(usable),
            False,
            "insufficient_causal_history",
        )
    closes = [bar.close for bar in usable[-lookback_bars - 1 :]]
    if any(price <= 0 for price in closes):
        return UnderlyingFeatures(
            asset_id,
            cadence_minutes,
            usable[-1].close_ts,
            None,
            None,
            None,
            len(usable),
            False,
            "invalid_price",
        )
    returns = [math.log(b.close / a.close) for a, b in pairwise(usable[-lookback_bars - 1 :])]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return UnderlyingFeatures(
        asset_id,
        cadence_minutes,
        usable[-1].close_ts,
        closes[-1],
        closes[-1] / closes[0] - 1,
        math.sqrt(variance),
        len(usable),
        True,
        "ok",
    )


__all__ = ["UnderlyingBar", "UnderlyingFeatures", "build_underlying_features"]
