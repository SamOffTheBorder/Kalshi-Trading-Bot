"""Fixed-fractional (`R`-based) position sizing for live orders.

Design decision D3 (v2): Kelly requires a trustworthy win-probability
estimate, and Phase 1's calibration table (model said 40% -> actually won
20%) proved that estimate does not exist yet. Kelly also compounds, which —
combined with phantom liquidity — produced a $172 position on a $130
bankroll. `kelly.py` stays in the tree for backtest comparison only; this
module sizes every live order.

The formula is the standard fixed-fractional-risk sizing used across
discretionary and systematic trading: risk a small, constant fraction of
equity per trade, sized by how far price must move against the position
before the stop is hit.

    R = |entry_price - stop_price|            (dollars, per contract/share)
    risk_dollars = equity * risk_pct
    size = risk_dollars / R                    (floored to whole units)

`risk_pct` is deliberately small (the documented tunable band is 1-2%,
matching design.md D3) and `max_position_pct` is a second, independent hard
cap applied after the R-based size — same min() clamp shape as
`kelly.size_binary_position`, so a degenerate (very tight) stop can never
alone justify an oversized position.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from kalshi_bot.signals.fees import TAKER_FEE_COEFFICIENT, entry_fee_dollars


@dataclass(frozen=True)
class FixedRiskConfig:
    """Sizing assumptions for the validation path.

    ``risk_pct`` is risk at the declared executable stop, while
    ``max_position_pct`` remains a notional safety cap.  Fees are included in
    the loss budget, so a stop cannot silently exceed the configured risk.
    """

    risk_pct: float = 0.01
    max_position_pct: float = 0.05
    fee_coefficient: float = TAKER_FEE_COEFFICIENT
    include_exit_fee: bool = True
    version: str = "2026-09-fixed-risk-v1"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def size_validation_position(
    *,
    equity_usd: float,
    entry_price_cents: int,
    stop_price_cents: int,
    config: FixedRiskConfig | None = None,
    target_price_cents: int | None = None,
    quantity_step: float = 1.0,
) -> float:
    """Size a validation trade from executable stop distance and full costs.

    The worst-case loss is the stop loss plus the entry fee and (when
    configured) the stop/exit fee.  ``quantity_step`` supports fractional
    instruments while preserving the legacy whole-contract default.
    """
    config = config or FixedRiskConfig()
    if equity_usd <= 0 or entry_price_cents <= 0 or stop_price_cents < 0:
        return 0.0
    if quantity_step <= 0:
        raise ValueError("quantity_step must be positive")
    if not 0.0 < config.risk_pct <= 1.0:
        raise ValueError("risk_pct must be in (0, 1]")
    if not 0.0 < config.max_position_pct <= 1.0:
        raise ValueError("max_position_pct must be in (0, 1]")
    entry = entry_price_cents / 100.0
    stop = stop_price_cents / 100.0
    distance = abs(entry - stop)
    if distance <= 0 or entry >= 1.0:
        return 0.0
    entry_fee = entry_fee_dollars(entry_price_cents, 1.0, coefficient=config.fee_coefficient)
    exit_fee = (
        entry_fee_dollars(stop_price_cents, 1.0, coefficient=config.fee_coefficient)
        if config.include_exit_fee
        else 0.0
    )
    loss_per_unit = distance + entry_fee + exit_fee
    if loss_per_unit <= 0:
        return 0.0
    risk_size = equity_usd * config.risk_pct / loss_per_unit
    notional_size = equity_usd * config.max_position_pct / (entry + entry_fee)
    raw = min(risk_size, notional_size)
    return max(0.0, (raw // quantity_step) * quantity_step)


def compute_r(entry_price: float, stop_price: float) -> float:
    """`R`: the dollar distance from entry to stop, per unit. Always positive
    regardless of the trade's direction — the caller already knows which
    side of entry the stop sits on."""
    r = abs(entry_price - stop_price)
    if r <= 0:
        raise ValueError("stop_price must differ from entry_price (R must be > 0)")
    return r


def size_fixed_risk(
    *,
    equity_usd: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float,
    max_position_pct: float,
    unit_cost: float | None = None,
) -> int:
    """Whole units to buy/sell so that a stop-out loses at most
    `equity_usd * risk_pct`, independent of `min()`-clamped against a hard
    cap of `equity_usd * max_position_pct` measured in notional dollars.

    `unit_cost` is the dollar cost to acquire one unit (e.g. the event-
    contract's price in dollars, or 1.0 for a perp priced directly in
    dollars-per-contract) — defaults to `entry_price` when the instrument's
    entry price and per-unit cost are the same thing (true for both event
    contracts and Kalshi perps). Pass it explicitly only when they diverge.

    Returns 0 for non-positive equity or a degenerate stop — never raises on
    bad *market* inputs, since a sizing function on the live path must fail
    safe to "don't trade" rather than crash the caller.
    """
    if equity_usd <= 0:
        return 0
    if not 0.0 < risk_pct <= 1.0:
        raise ValueError("risk_pct must be in (0, 1]")
    if not 0.0 < max_position_pct <= 1.0:
        raise ValueError("max_position_pct must be in (0, 1]")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    r = abs(entry_price - stop_price)
    if r <= 0:
        return 0

    risk_dollars = equity_usd * risk_pct
    r_based_size = risk_dollars / r

    cost_per_unit = unit_cost if unit_cost is not None else entry_price
    if cost_per_unit <= 0:
        raise ValueError("unit_cost must be positive")
    max_notional_size = (equity_usd * max_position_pct) / cost_per_unit

    return int(min(r_based_size, max_notional_size))


__all__ = ["FixedRiskConfig", "compute_r", "size_fixed_risk", "size_validation_position"]
