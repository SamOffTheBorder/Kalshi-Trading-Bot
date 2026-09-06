"""Level-break (breakout continuation) strategy (tasks.md 6.2, design D2,
spec-selected 2.3 — subsumes opening-range-breakout, since a 24/7 15-minute
binary has no real "session open" to anchor an ORB to).

Where `trend_scalp.py` buys a PULLBACK to a level that has held, this
strategy buys the BREAK of a level that has NOT held, with volume
confirmation: a swing high/low is breached (closed through, the opposite of
`levels.level_is_respected`) on volume meaningfully above its recent
average — the confirmation that distinguishes a genuine breakout from a
low-conviction wick that will likely mean-revert.

Same scope note as trend_scalp.py: decision-level only (tasks.md 6.2).
`BacktestEngine` does not yet simulate intrabar stop/target management;
this strategy's stop/target are expressed in underlying-spot terms for a
later engine change to consume.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.strategy.base import Action, Decision, StrategyContext
from kalshi_bot.strategy.levels import (
    SpotBar,
    SwingLevel,
    find_swing_levels,
    spot_r_to_contract_cents,
)


@dataclass(frozen=True)
class LevelBreakConfig:
    lookback_bars: int = 20
    level_tolerance_pct: float = 0.003
    min_touches: int = 2
    volume_confirmation_multiple: float = 1.5
    """Breakout bar's volume must be at least this multiple of the average
    volume over `volume_lookback_bars` preceding it."""
    volume_lookback_bars: int = 10
    r_multiple_target: float = 1.5
    min_minutes_to_expiry: float = 10.0


class LevelBreakStrategy:
    name = "level_break"

    def __init__(self, config: LevelBreakConfig | None = None) -> None:
        self.config = config or LevelBreakConfig()

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
        bars = list(context.spot_bars)
        if len(bars) < cfg.volume_lookback_bars + 1:
            return hold("insufficient_bar_history")
        if context.yes_ask_cents is None or context.yes_bid_cents is None:
            return hold("no_quotes")

        # Levels computed on history EXCLUDING the current (possibly
        # breaking) bar — a level can't confirm itself by including the
        # breakout bar in its own detection window.
        history = bars[:-1]
        breakout_bar = bars[-1]
        levels = find_swing_levels(
            history,
            lookback=cfg.lookback_bars,
            tolerance_pct=cfg.level_tolerance_pct,
            min_touches=cfg.min_touches,
        )
        if not levels:
            return hold("no_level_in_range")

        recent_volumes = [b.volume for b in bars[-1 - cfg.volume_lookback_bars : -1]]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0.0
        if avg_volume <= 0 or breakout_bar.volume < cfg.volume_confirmation_multiple * avg_volume:
            return hold("volume_not_confirmed")

        # A resistance (high) broken by closing above it -> bullish
        # continuation; a support (low) broken by closing below it ->
        # bearish continuation. Only the CLOSEST broken level in each
        # direction matters — a distant, already-broken level from earlier
        # history is not this bar's breakout.
        broken_high = _closest_broken(levels, breakout_bar, kind="high")
        broken_low = _closest_broken(levels, breakout_bar, kind="low")

        if broken_high is None and broken_low is None:
            return hold("no_breakout")
        if broken_high is not None and broken_low is not None:
            # Both directions broken in one bar (a very wide range bar) —
            # ambiguous, decline rather than guess.
            return hold("ambiguous_breakout")

        entry_price = breakout_bar.close
        if broken_high is not None:
            stop_price = broken_high.price
            action, entry_cents, side = Action.BUY_YES, context.yes_ask_cents, "yes"
        else:
            assert broken_low is not None
            stop_price = broken_low.price
            action, entry_cents, side = Action.BUY_NO, 100 - context.yes_bid_cents, "no"

        r = abs(entry_price - stop_price)
        if r <= 0:
            return hold("degenerate_r")
        target_price = (
            entry_price + cfg.r_multiple_target * r
            if action == Action.BUY_YES
            else entry_price - cfg.r_multiple_target * r
        )

        stop_price_cents = spot_r_to_contract_cents(
            entry_price, stop_price, entry_cents, side=side
        )
        target_price_cents = spot_r_to_contract_cents(
            entry_price, target_price, entry_cents, side=side
        )

        return Decision(
            action=action,
            market_ticker=context.market_ticker,
            strategy_name=self.name,
            entry_price_cents=entry_cents,
            stop_price=stop_price,
            target_price=target_price,
            stop_price_cents=stop_price_cents,
            target_price_cents=target_price_cents,
        )


def _closest_broken(
    levels: list[SwingLevel], breakout_bar: SpotBar, *, kind: str
) -> SwingLevel | None:
    candidates = [lvl for lvl in levels if lvl.kind == kind]
    if kind == "high":
        broken = [lvl for lvl in candidates if breakout_bar.close > lvl.price]
        if not broken:
            return None
        return min(broken, key=lambda lvl: breakout_bar.close - lvl.price)
    broken = [lvl for lvl in candidates if breakout_bar.close < lvl.price]
    if not broken:
        return None
    return min(broken, key=lambda lvl: lvl.price - breakout_bar.close)


__all__ = ["LevelBreakConfig", "LevelBreakStrategy"]
