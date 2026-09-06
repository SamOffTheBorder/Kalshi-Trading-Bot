"""Funding-carry strategy (tasks.md 6.3, design.md fallback priority,
strategy-research.md §4, spec-selected 2.3).

Genuinely market-neutral "cash and carry": take the side of the perp that
RECEIVES funding, and hedge the resulting directional exposure with an
event contract on the same underlying index (design.md's stated rationale
for this being coherent on Kalshi specifically — both instruments track the
same reference index, BRTI for BTC). P&L is the funding collected, net of
hedge-leg cost/slippage/fees on both legs — NOT a win-rate strategy, unlike
`trend_scalp`/`level_break`. Falsified (strategy-research.md §4) if realized
funding, net of both legs' transaction costs, does not exceed the return of
just holding cash.

**Does not fit `StrategyProtocol`** (`strategy/base.py`): that protocol is
single-instrument, single-decision (`Decision.action` buys/holds one
market). Funding carry inherently spans two instruments (a perp + an event
contract) with two coordinated legs, so this module has its own
`evaluate_funding_carry()` / `FundingCarryDecision` rather than shoehorning
a two-leg trade into a one-instrument `Decision`.

Reuses `risk/funding_awareness.py`'s `FundingState` (tasks.md 5.5) for the
funding-rate input rather than re-deriving it — the "does this position pay
or receive" computation is identical logic either way. Reuses
`signals/fees.py`'s fee model for the event-contract hedge leg's cost.

**Finding from building this (2026-09-06):** the hedge leg's fee drag is
substantial at Kalshi's rates. `entry_fee_rate_at_price` peaks at a 50c
contract (coefficient * P * (1-P) is maximized at P=0.5) — precisely where
design.md recommends hedging for the most linear BRTI-tracking delta. A
$10,000 notional hedged with 50c contracts needs 20,000 of them at ~1.75c
fee each, ~$350 of fee drag alone; collecting that back needs a funding
rate north of 3.5% on that notional just to break even on the hedge leg
alone, before the perp side's own costs. This is exactly the falsification
strategy-research.md §4 anticipated ("falsified if realized funding, net of
hedge-leg transaction costs, does not exceed...") — real-world funding-carry
entries need EITHER a genuinely extreme funding rate, or a hedge contract
priced away from 50c (less delta-accurate, more fee-efficient), or both.
`min_funding_rate_abs`'s default is deliberately conservative for this
reason.

**Scope note (decision-level only, same as 6.1/6.2):** produces a decision
to open (or not open) a hedged position and its expected net carry. Does
not place orders, does not manage the hedge over the position's life, and
is not wired into `BacktestEngine` — funding-carry backtesting needs perps
funding-rate history (tasks.md 1.4/4.4) the engine does not yet load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kalshi_bot.risk.funding_awareness import FundingState
from kalshi_bot.signals.fees import TAKER_FEE_COEFFICIENT, entry_fee_rate_at_price

PerpSide = Literal["long", "short"]


@dataclass(frozen=True)
class FundingCarryConfig:
    min_funding_rate_abs: float = 0.0003
    """Minimum |funding_rate| (per funding period) worth collecting at all —
    below this, the trade is not attempted regardless of cost, since a tiny
    rate can never clear two legs' worth of transaction costs."""
    hedge_contract_cost_dollars: float = 0.50
    """Cost (dollars per contract) to open the event-contract hedge leg —
    the near-the-money event contract's price; the strategy is expected to
    pick a hedge contract close to 50c since that's where BRTI-tracking
    delta is most linear, matching design.md's rationale for using an event
    contract at all instead of spot."""
    hedge_fee_rate: float = TAKER_FEE_COEFFICIENT
    min_expected_net_carry_usd: float = 0.0
    """Gate: expected funding collected minus both legs' costs must exceed
    this before entering. Zero means "must be non-negative"; set positive
    for a margin of safety over the bare breakeven."""


@dataclass(frozen=True)
class FundingCarryDecision:
    should_enter: bool
    reason: str
    perp_side: PerpSide | None = None
    """Which side of the PERP to hold. The strategy always takes the side
    that RECEIVES funding: long when funding_rate < 0 (shorts pay longs
    under the assumed convention — see funding_awareness.py's caveat), short
    when funding_rate > 0."""
    expected_funding_usd: float | None = None
    hedge_cost_usd: float | None = None
    expected_net_carry_usd: float | None = None


def evaluate_funding_carry(
    funding_state: FundingState,
    *,
    position_notional_usd: float,
    config: FundingCarryConfig | None = None,
) -> FundingCarryDecision:
    """Decide whether to open a funding-carry position sized at
    `position_notional_usd` (the perp leg's notional; the hedge leg is sized
    to offset that notional's directional exposure — sizing the hedge leg's
    CONTRACT COUNT from notional is the caller's job, since it depends on
    the specific event contract chosen, not this function's).
    """
    cfg = config or FundingCarryConfig()
    if cfg.hedge_contract_cost_dollars <= 0:
        raise ValueError("hedge_contract_cost_dollars must be positive")

    if abs(funding_state.funding_rate) < cfg.min_funding_rate_abs:
        return FundingCarryDecision(should_enter=False, reason="funding_rate_too_small")

    # Take the side that RECEIVES: funding_state was computed for a specific
    # side already, but the carry strategy is free to choose either side of
    # the perp — pick whichever receives under the observed rate.
    perp_side: PerpSide = "short" if funding_state.funding_rate > 0 else "long"
    expected_funding_usd = abs(position_notional_usd * funding_state.funding_rate)

    # Number of $1-payout event contracts needed so the hedge leg's notional
    # matches the perp leg's, at the configured hedge contract price.
    hedge_contract_count = position_notional_usd / cfg.hedge_contract_cost_dollars
    fee_rate_per_contract = entry_fee_rate_at_price(
        cfg.hedge_contract_cost_dollars, coefficient=cfg.hedge_fee_rate
    )
    # The hedge leg's cost is the fee only, not the contract price itself —
    # the contract price is capital allocated, recovered at settlement (or
    # by closing the hedge), whereas the fee is the actual carry cost, same
    # accounting `crypto_mispricing`/`kelly.py` use for the event-contract
    # side (fee is the cost that erodes edge, not the notional at risk).
    hedge_cost_usd = hedge_contract_count * fee_rate_per_contract

    expected_net_carry_usd = expected_funding_usd - hedge_cost_usd

    if expected_net_carry_usd <= cfg.min_expected_net_carry_usd:
        return FundingCarryDecision(
            should_enter=False,
            reason="net_carry_below_gate",
            perp_side=perp_side,
            expected_funding_usd=expected_funding_usd,
            hedge_cost_usd=hedge_cost_usd,
            expected_net_carry_usd=expected_net_carry_usd,
        )

    return FundingCarryDecision(
        should_enter=True,
        reason="funding_carry_favorable",
        perp_side=perp_side,
        expected_funding_usd=expected_funding_usd,
        hedge_cost_usd=hedge_cost_usd,
        expected_net_carry_usd=expected_net_carry_usd,
    )


__all__ = ["FundingCarryConfig", "FundingCarryDecision", "PerpSide", "evaluate_funding_carry"]
