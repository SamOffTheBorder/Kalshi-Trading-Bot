"""Fractional Kelly sizing for binary contracts.

Kept for backtest comparison only (design decision D3, v2) — Kelly does not
size live orders; `risk/fixed_risk.py` does.

Full Kelly for a binary bet at cost `c` (dollars, wins pay $1) with win
probability `p` and net odds `b`:

    f* = p - (1 - p) / b        where b = payout / cost

With no fee, b = (1-c)/c and this reduces to the classic (p - c) / (1 - c).
Kalshi's fee is charged ONCE, AT ENTRY, win or lose (see signals/fees.py)
— it raises the effective cost basis, it does NOT cut the payout. Effective
cost c' = c + fee(c); the classic formula is then applied to c' with the
full $1 payout intact: b = (1-c')/c'.
"""

from __future__ import annotations

from kalshi_bot.signals.fees import TAKER_FEE_COEFFICIENT, entry_fee_rate_at_price

KALSHI_FEE_RATE = TAKER_FEE_COEFFICIENT  # re-exported for backward compat


def binary_kelly_fraction(
    p_win: float,
    cost_dollars: float,
    *,
    fee_rate: float = TAKER_FEE_COEFFICIENT,
) -> float:
    """Full-Kelly optimal fraction of bankroll. 0.0 when there is no edge."""
    if not 0.0 <= p_win <= 1.0:
        raise ValueError("p_win must be in [0, 1]")
    if not 0.0 < cost_dollars < 1.0:
        raise ValueError("cost_dollars must be in (0, 1)")
    effective_cost = cost_dollars + entry_fee_rate_at_price(cost_dollars, coefficient=fee_rate)
    if effective_cost <= 0.0 or effective_cost >= 1.0:
        return 0.0
    net_odds = (1.0 - effective_cost) / effective_cost
    if net_odds <= 0:
        return 0.0
    f_star = p_win - (1.0 - p_win) / net_odds
    return max(0.0, f_star)


def size_binary_position(
    *,
    p_win: float,
    cost_cents: int,
    bankroll_usd: float,
    kelly_fraction: float,
    max_position_pct: float,
    fee_rate: float = KALSHI_FEE_RATE,
) -> int:
    """Number of contracts to buy. Applies fractional Kelly, then the hard cap,
    then floors to whole contracts. Returns 0 on no edge / dust bankrolls."""
    if bankroll_usd <= 0:
        return 0
    cost_dollars = cost_cents / 100
    full_kelly = binary_kelly_fraction(p_win, cost_dollars, fee_rate=fee_rate)
    if full_kelly <= 0.0:
        return 0
    fraction = min(kelly_fraction * full_kelly, max_position_pct)  # the clamp
    budget = bankroll_usd * fraction
    # Actual dollar outlay per contract is price + entry fee, not price alone
    # (see signals/fees.py) — using price alone overstates how many
    # contracts the budget can afford.
    effective_cost_dollars = cost_dollars + entry_fee_rate_at_price(
        cost_dollars, coefficient=fee_rate
    )
    return int(budget // effective_cost_dollars)
