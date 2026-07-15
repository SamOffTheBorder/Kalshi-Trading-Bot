"""Fractional Kelly sizing for binary contracts.

Full Kelly for a binary bet at cost `c` (dollars, wins pay $1) with win
probability `p` and net odds `b`:

    f* = p - (1 - p) / b        where b = payout / cost

With no fee, b = (1-c)/c and this reduces to the classic (p - c) / (1 - c).
We size on FEE-ADJUSTED odds (Kalshi keeps 7% of net winnings), so the
formula the money actually experiences is the one used.

Two layers of restraint, both non-negotiable:
1. `kelly_fraction` (quarter-Kelly default) — edge estimates are uncertain.
2. `max_position_pct` hard cap applied AFTER Kelly as a min() clamp — no
   configuration or Kelly output can exceed it.
"""

from __future__ import annotations

KALSHI_FEE_RATE = 0.07


def binary_kelly_fraction(
    p_win: float,
    cost_dollars: float,
    *,
    fee_rate: float = KALSHI_FEE_RATE,
) -> float:
    """Full-Kelly optimal fraction of bankroll. 0.0 when there is no edge."""
    if not 0.0 <= p_win <= 1.0:
        raise ValueError("p_win must be in [0, 1]")
    if not 0.0 < cost_dollars < 1.0:
        raise ValueError("cost_dollars must be in (0, 1)")
    net_odds = ((1.0 - cost_dollars) * (1.0 - fee_rate)) / cost_dollars
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
    return int(budget // cost_dollars)
