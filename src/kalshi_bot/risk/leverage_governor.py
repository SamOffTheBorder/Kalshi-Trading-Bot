"""Leverage governor for perps positions (tasks.md 5.3, spec: perps-trading).

Two independent checks, both required before an entry is allowed:

1. **Leverage ceiling** ("Leverage ceiling below exchange maximum"): effective
   leverage is capped at 2x by default with a hard ceiling of 3x, regardless
   of whatever higher maximum Kalshi itself permits. The ceiling is
   deliberately *below* the exchange limit — this bot chooses a tighter
   number, it does not merely inherit the venue's.

2. **Liquidation buffer** ("Liquidation buffer enforcement"): an entry is
   refused whenever its stop-loss sits at or beyond the position's
   liquidation price, so the stop is always reached (and the position closed
   on the bot's own terms) strictly before the exchange would liquidate it
   out from under the bot at a worse price.

Field names below (`account_leverage`, `position_leverage`,
`estimated_liquidation_price`, `mark_price`) match
`KalshiMarginClient.get_risk()`'s real response shape, verified against
`docs.kalshi.com/margin-rest/risk/get-risk.md` 2026-09-06 — this module
consumes that dict directly rather than redefining its own risk schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

DEFAULT_LEVERAGE_CAP = 2.0
HARD_LEVERAGE_CEILING = 3.0


@dataclass(frozen=True)
class LeverageCheckResult:
    allowed: bool
    reason: str | None = None
    implied_leverage: float | None = None


@dataclass(frozen=True)
class LiquidationBufferResult:
    allowed: bool
    reason: str | None = None
    distance_to_liquidation: float | None = None
    stop_distance: float | None = None


def check_leverage_ceiling(
    *,
    position_notional_usd: float,
    equity_usd: float,
    leverage_cap: float = DEFAULT_LEVERAGE_CAP,
) -> LeverageCheckResult:
    """Reject a position whose implied leverage (notional / equity) exceeds
    `leverage_cap`. `leverage_cap` itself is clamped to never exceed
    `HARD_LEVERAGE_CEILING` — a caller cannot configure their way past the
    hard ceiling even by mistake, since `Settings.max_leverage` (or whatever
    config feeds this) might otherwise be set carelessly."""
    if equity_usd <= 0:
        return LeverageCheckResult(allowed=False, reason="non-positive equity")
    effective_cap = min(leverage_cap, HARD_LEVERAGE_CEILING)
    implied_leverage = position_notional_usd / equity_usd
    if implied_leverage > effective_cap:
        return LeverageCheckResult(
            allowed=False,
            reason=(
                f"implied leverage {implied_leverage:.2f}x exceeds cap {effective_cap:.2f}x"
            ),
            implied_leverage=implied_leverage,
        )
    return LeverageCheckResult(allowed=True, implied_leverage=implied_leverage)


def max_notional_for_leverage_cap(
    *, equity_usd: float, leverage_cap: float = DEFAULT_LEVERAGE_CAP
) -> float:
    """The largest position notional (dollars) allowed under the leverage
    cap for the given equity — useful for sizing an entry down to fit,
    rather than only rejecting it after the fact."""
    if equity_usd <= 0:
        return 0.0
    effective_cap = min(leverage_cap, HARD_LEVERAGE_CEILING)
    return equity_usd * effective_cap


def check_liquidation_buffer(
    *,
    entry_price: float,
    stop_price: float,
    liquidation_price: float,
    side: Literal["long", "short"],
) -> LiquidationBufferResult:
    """Refuse an entry whose stop sits at or beyond the liquidation price —
    i.e. the exchange would liquidate the position at or before the bot's
    own stop would fire, defeating the point of having a stop at all.

    For a long, liquidation sits below entry and the stop must sit strictly
    above liquidation. For a short, liquidation sits above entry and the
    stop must sit strictly below it."""
    stop_distance = abs(entry_price - stop_price)
    distance_to_liquidation = abs(entry_price - liquidation_price)

    if side == "long":
        stop_inside_liquidation_zone = stop_price <= liquidation_price
    else:
        stop_inside_liquidation_zone = stop_price >= liquidation_price

    if stop_inside_liquidation_zone or stop_distance >= distance_to_liquidation:
        return LiquidationBufferResult(
            allowed=False,
            reason=(
                f"stop distance {stop_distance:.4g} reaches or exceeds distance to "
                f"liquidation {distance_to_liquidation:.4g} ({side} @ entry={entry_price}, "
                f"stop={stop_price}, liquidation={liquidation_price})"
            ),
            distance_to_liquidation=distance_to_liquidation,
            stop_distance=stop_distance,
        )
    return LiquidationBufferResult(
        allowed=True,
        distance_to_liquidation=distance_to_liquidation,
        stop_distance=stop_distance,
    )


def find_position_risk(risk_response: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    """Pull one market's entry out of `KalshiMarginClient.get_risk()`'s
    `positions` list. Returns None if the ticker has no open position."""
    for position in risk_response.get("positions", []):
        if position.get("market_ticker") == ticker:
            return position
    return None


def liquidation_price_from_risk(position_risk: dict[str, Any]) -> float | None:
    """Extract `estimated_liquidation_price` as a float, or None when the
    exchange hasn't provided one (nullable per the API schema — e.g. a
    freshly opened or portfolio-margined position might not have settled
    on an estimate yet)."""
    raw = position_risk.get("estimated_liquidation_price")
    if raw is None:
        return None
    return float(Decimal(str(raw)))


__all__ = [
    "DEFAULT_LEVERAGE_CAP",
    "HARD_LEVERAGE_CEILING",
    "LeverageCheckResult",
    "LiquidationBufferResult",
    "check_leverage_ceiling",
    "check_liquidation_buffer",
    "find_position_risk",
    "liquidation_price_from_risk",
    "max_notional_for_leverage_cap",
]
