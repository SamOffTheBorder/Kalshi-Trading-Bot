"""Trend-scalp strategy (tasks.md 6.1, design D2, spec-selected 2.3): trade
WITH short-term momentum, enter on a pullback to a level that has held, exit
fast at a fixed R target.

Design D2's posture inversion from v1: the zero-drift pricer loses by
fading trends (Phase 1 run #6 OOS: 32.1% win vs 46.2% breakeven). This
strategy does the opposite of `crypto_mispricing`: it requires a trend
(`trend_zscore` beyond a minimum, same signed z-score `StrategyContext`
already provides), then waits for price to pull back to a *respected*
level (design D2, `strategy/levels.py`) in the trend's direction before
entering — buying the pullback, not fading the move.

**Scope note (decision-level only, tasks.md 6.1):** this strategy produces
entry decisions with `stop_price`/`target_price` in underlying-spot terms.
It does not simulate intrabar stop/target management — `BacktestEngine`
does not yet support that (a materially different execution model from
crypto_mispricing's settle-at-expiry loop); wiring it in is separate,
larger backtest-engine work, not done here. Known-answer unit tests
(tasks.md 6.5) exercise `evaluate()` directly against synthetic bars.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.strategy.base import Action, Decision, StrategyContext
from kalshi_bot.strategy.levels import (
    find_swing_levels,
    level_is_respected,
    spot_r_to_contract_cents,
)


@dataclass(frozen=True)
class TrendScalpConfig:
    min_trend_zscore: float = 0.5
    """Trend must be at least this strong (in the SAME direction the trade
    would take) before a pullback entry is even considered — the mirror
    image of crypto_mispricing's max_trend_zscore gate, which instead HOLDs
    above this magnitude."""
    lookback_bars: int = 20
    level_tolerance_pct: float = 0.003
    min_touches: int = 2
    r_multiple_target: float = 1.5
    """Target distance as a multiple of R (the stop distance) — e.g. 1.5
    means the target is 1.5x as far from entry as the stop."""
    min_minutes_to_expiry: float = 10.0


class TrendScalpStrategy:
    name = "trend_scalp"

    def __init__(self, config: TrendScalpConfig | None = None) -> None:
        self.config = config or TrendScalpConfig()

    def evaluate(self, context: StrategyContext) -> Decision:
        cfg = self.config

        def hold(reason: str) -> Decision:
            return Decision(
                action=Action.HOLD,
                market_ticker=context.market_ticker,
                strategy_name=self.name,
                hold_reason=reason,
            )

        if context.minutes_to_expiry < cfg.min_minutes_to_expiry:
            return hold("too_close_to_expiry")
        if context.trend_zscore is None:
            return hold("no_trend_signal")
        if abs(context.trend_zscore) < cfg.min_trend_zscore:
            return hold("trend_too_weak")
        if len(context.spot_bars) < 2:
            return hold("insufficient_bar_history")
        if context.yes_ask_cents is None or context.yes_bid_cents is None:
            return hold("no_quotes")

        trending_up = context.trend_zscore > 0
        levels = find_swing_levels(
            list(context.spot_bars),
            lookback=cfg.lookback_bars,
            tolerance_pct=cfg.level_tolerance_pct,
            min_touches=cfg.min_touches,
        )
        # An uptrend pulls back to a LOW (support) that has held; a
        # downtrend pulls back to a HIGH (resistance) that has held.
        relevant_kind = "low" if trending_up else "high"
        candidates = [lvl for lvl in levels if lvl.kind == relevant_kind]
        if not candidates:
            return hold("no_level_in_range")

        last_bar = context.spot_bars[-1]
        approach_price = last_bar.low if trending_up else last_bar.high
        respected_level = next(
            (
                lvl
                for lvl in candidates
                if level_is_respected(lvl, approach_price, last_bar.close, cfg.level_tolerance_pct)
            ),
            None,
        )
        if respected_level is None:
            return hold("level_not_respected")

        entry_price = last_bar.close
        stop_price = respected_level.price
        r = abs(entry_price - stop_price)
        if r <= 0:
            return hold("degenerate_r")
        target_price = (
            entry_price + cfg.r_multiple_target * r
            if trending_up
            else entry_price - cfg.r_multiple_target * r
        )

        # Trading with an uptrend means betting the underlying finishes
        # higher -> BUY_YES on a "greater than" style contract (or BUY_NO on
        # a "less than" contract trends toward); the caller's market
        # selection is expected to already match direction to contract
        # shape (tasks.md 6.1 scope: decision-level only). Here we express
        # direction as YES for an uptrend, NO for a downtrend, consistent
        # with `crypto_mispricing`'s convention that YES means "the
        # underlying condition resolves true."
        if trending_up:
            action, entry_cents, side = Action.BUY_YES, context.yes_ask_cents, "yes"
        else:
            action, entry_cents, side = Action.BUY_NO, 100 - context.yes_bid_cents, "no"

        # Side-consistent fair probability (kxbtc15m-validation-rebuild §2.3:
        # every BUY must carry one; the engine no longer infers certainty from
        # a missing value). This strategy has no probability model of its own —
        # per the rebuild's design, short-horizon trend is a *conditional
        # feature* on top of the settlement-aware baseline (task 4.x), not a
        # standalone edge. Until that baseline exists, the honest estimate is
        # the contract's own executable price read as an implied probability:
        # it makes fixed-risk sizing degenerate to ~zero edge (correct — an
        # unproven signal should not size up) while still being a valid,
        # side-consistent number rather than a 1.0 sure-thing.
        fair_probability = entry_cents / 100

        stop_price_cents = spot_r_to_contract_cents(entry_price, stop_price, entry_cents, side=side)
        target_price_cents = spot_r_to_contract_cents(
            entry_price, target_price, entry_cents, side=side
        )

        return Decision(
            action=action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            fair_probability=fair_probability,
            entry_price_cents=entry_cents,
            stop_price=stop_price,
            target_price=target_price,
            stop_price_cents=stop_price_cents,
            target_price_cents=target_price_cents,
        )


__all__ = ["TrendScalpConfig", "TrendScalpStrategy"]
