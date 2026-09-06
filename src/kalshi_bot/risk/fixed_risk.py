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


__all__ = ["compute_r", "size_fixed_risk"]
