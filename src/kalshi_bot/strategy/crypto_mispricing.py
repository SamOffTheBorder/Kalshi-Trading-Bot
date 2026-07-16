"""Crypto mispricing strategy: fair value vs. market price on Kalshi
threshold/range contracts.

Successor to v1's aggregator with its verified-correct core preserved:
Black-Scholes digital pricing as the anchor, Monte Carlo as a disagreement
guard, and — critically — the fee subtracted from edge BEFORE any gate.
v1 went live on a raw edge that evaporated after fees; that failure mode is
structurally excluded here.

Edge definition (per contract dollar):
    EV_yes = p * (1 - c) * (1 - fee_rate) - (1 - p) * c
where p = model win probability, c = entry price in dollars. Kalshi's fee is
7% of net winnings, charged only on wins.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.signals.black_scholes import contract_probability
from kalshi_bot.signals.monte_carlo import terminal_spot_probability
from kalshi_bot.strategy.base import Action, Decision, StrategyContext

KALSHI_FEE_RATE = 0.07


def fee_adjusted_ev(p_win: float, cost_dollars: float, fee_rate: float = KALSHI_FEE_RATE) -> float:
    """Expected value per contract, fee on net winnings, in dollars."""
    gross_win = 1.0 - cost_dollars
    return p_win * gross_win * (1.0 - fee_rate) - (1.0 - p_win) * cost_dollars


@dataclass(frozen=True)
class CryptoMispricingConfig:
    min_edge: float = 0.05
    max_model_divergence: float = 0.06
    min_entry_probability: float = 0.30
    max_entry_probability: float = 0.80
    min_minutes_to_expiry: float = 10.0
    max_trend_zscore: float = 1.5
    mc_paths: int = 20_000
    mc_seed: int | None = None  # set for deterministic backtests


class CryptoMispricingStrategy:
    name = "crypto_mispricing"

    def __init__(self, config: CryptoMispricingConfig | None = None) -> None:
        self.config = config or CryptoMispricingConfig()

    def evaluate(self, context: StrategyContext) -> Decision:
        cfg = self.config

        def hold(
            reason: str,
            *,
            bs_probability: float | None = None,
            mc_probability: float | None = None,
            raw_edge: float | None = None,
            fee_adjusted_edge: float | None = None,
        ) -> Decision:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason=reason,
                bs_probability=bs_probability,
                mc_probability=mc_probability,
                raw_edge=raw_edge,
                fee_adjusted_edge=fee_adjusted_edge,
            )

        if context.minutes_to_expiry < cfg.min_minutes_to_expiry:
            return hold("too_close_to_expiry")
        if context.yes_ask_cents is None or context.yes_bid_cents is None:
            return hold("no_quotes")
        if not (0 < context.yes_ask_cents < 100) or not (0 <= context.yes_bid_cents < 100):
            return hold("degenerate_quotes")
        # Zero-drift BS/MC cannot price a trending market — run #4's audit showed
        # every loss came from repeatedly fading one directional move. When recent
        # realized drift exceeds what the model's own vol expects, stand down.
        if context.trend_zscore is not None and abs(context.trend_zscore) > cfg.max_trend_zscore:
            return hold("trend_regime")

        try:
            bs = contract_probability(
                spot=context.spot,
                strike_type=context.strike_type,
                floor_strike=context.floor_strike,
                cap_strike=context.cap_strike,
                vol_annual=context.vol_annual,
                t_years=context.t_years,
            )
            mc = terminal_spot_probability(
                spot=context.spot,
                strike_type=context.strike_type,
                floor_strike=context.floor_strike,
                cap_strike=context.cap_strike,
                vol_annual=context.vol_annual,
                t_years=context.t_years,
                n_paths=cfg.mc_paths,
                seed=cfg.mc_seed,
            )
        except ValueError as exc:
            return hold(f"pricing_error:{exc}")

        divergence = abs(bs - mc)
        if divergence > cfg.max_model_divergence:
            return hold("bs_mc_divergence", bs_probability=bs, mc_probability=mc)

        # YES side: pay the ask, win probability = p
        yes_cost = context.yes_ask_cents / 100
        ev_yes = fee_adjusted_ev(bs, yes_cost)
        raw_yes = bs - yes_cost

        # NO side: NO ask = 100 - yes_bid; win probability = 1 - p
        no_cost = (100 - context.yes_bid_cents) / 100
        ev_no = fee_adjusted_ev(1.0 - bs, no_cost)
        raw_no = (1.0 - bs) - no_cost

        if ev_yes >= ev_no:
            action, ev, raw, p_win = Action.BUY_YES, ev_yes, raw_yes, bs
            entry_cents = context.yes_ask_cents
        else:
            action, ev, raw, p_win = Action.BUY_NO, ev_no, raw_no, 1.0 - bs
            entry_cents = 100 - context.yes_bid_cents

        if ev < cfg.min_edge:
            reason = "insufficient_edge"
        elif p_win < cfg.min_entry_probability:
            reason = "probability_below_floor"
        elif p_win > cfg.max_entry_probability:
            reason = "probability_above_ceiling"
        else:
            reason = None

        if reason is not None:
            return hold(
                reason,
                bs_probability=bs,
                mc_probability=mc,
                raw_edge=raw,
                fee_adjusted_edge=ev,
            )

        confidence = min(1.0, ev / (2 * cfg.min_edge))
        return Decision(
            action=action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            confidence=confidence,
            entry_price_cents=entry_cents,
            bs_probability=bs,
            mc_probability=mc,
            raw_edge=raw,
            fee_adjusted_edge=ev,
        )
