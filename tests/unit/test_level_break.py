"""Level-break strategy: known-answer tests (tasks.md 6.2/6.5)."""

from __future__ import annotations

import dataclasses

from kalshi_bot.strategy.base import Action, StrategyContext
from kalshi_bot.strategy.level_break import LevelBreakConfig, LevelBreakStrategy
from kalshi_bot.strategy.levels import SpotBar


def _bar(ts: int, price: float, *, volume: float = 1.0) -> SpotBar:
    return SpotBar(ts=ts, open=price, high=price, low=price, close=price, volume=volume)


def _context(bars: list[SpotBar], **overrides: object) -> StrategyContext:
    base = StrategyContext(
        market_ticker="KXBTC15M-TEST",
        series_ticker="KXBTC15M",
        strike_type="greater",
        floor_strike=100.0,
        cap_strike=None,
        now_ts=1000,
        close_ts=1000 + 900,
        yes_bid_cents=48,
        yes_ask_cents=52,
        spot=bars[-1].close if bars else 100.0,
        vol_annual=0.6,
        vol_source="test",
        trend_zscore=None,
        spot_bars=tuple(bars),
    )
    return dataclasses.replace(base, **overrides)


def _resistance_break_bars(breakout_volume: float = 10.0) -> list[SpotBar]:
    # Confirmed resistance around 105 (two touches), consolidation with low
    # volume, then a high-volume close above it.
    prices = [100, 102, 105, 102, 100, 101, 105.1, 101, 100]
    bars = [_bar(i, p, volume=1.0) for i, p in enumerate(prices)]
    bars.append(_bar(len(bars), 108, volume=breakout_volume))
    return bars


def test_holds_when_too_close_to_expiry():
    strat = LevelBreakStrategy()
    bars = _resistance_break_bars()
    context = _context(bars, now_ts=1000, close_ts=1000 + 60)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "too_close_to_expiry"


def test_holds_on_insufficient_bar_history():
    strat = LevelBreakStrategy(LevelBreakConfig(volume_lookback_bars=10))
    context = _context([_bar(0, 100)])
    decision = strat.evaluate(context)
    assert decision.hold_reason == "insufficient_bar_history"


def test_resistance_break_with_volume_confirmation_enters_buy_yes():
    cfg = LevelBreakConfig(
        lookback_bars=2,
        level_tolerance_pct=0.01,
        min_touches=2,
        volume_lookback_bars=8,
        volume_confirmation_multiple=1.5,
    )
    strat = LevelBreakStrategy(cfg)
    bars = _resistance_break_bars(breakout_volume=10.0)
    context = _context(bars)
    decision = strat.evaluate(context)
    assert decision.action == Action.BUY_YES
    assert decision.entry_price_cents == 52
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.target_price > decision.stop_price
    assert decision.stop_price_cents is not None
    assert decision.target_price_cents is not None
    assert decision.target_price_cents >= decision.entry_price_cents
    assert decision.stop_price_cents <= decision.entry_price_cents


def test_holds_when_volume_not_confirmed():
    cfg = LevelBreakConfig(
        lookback_bars=2,
        level_tolerance_pct=0.01,
        min_touches=2,
        volume_lookback_bars=8,
        volume_confirmation_multiple=1.5,
    )
    strat = LevelBreakStrategy(cfg)
    bars = _resistance_break_bars(breakout_volume=1.0)  # same as average -> not confirmed
    context = _context(bars)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "volume_not_confirmed"


def test_support_break_with_volume_confirmation_enters_buy_no():
    prices = [100, 98, 95, 98, 100, 99, 94.9, 99, 100]
    bars = [_bar(i, p, volume=1.0) for i, p in enumerate(prices)]
    bars.append(_bar(len(bars), 90, volume=10.0))
    cfg = LevelBreakConfig(
        lookback_bars=2,
        level_tolerance_pct=0.01,
        min_touches=2,
        volume_lookback_bars=8,
        volume_confirmation_multiple=1.5,
    )
    strat = LevelBreakStrategy(cfg)
    context = _context(bars)
    decision = strat.evaluate(context)
    assert decision.action == Action.BUY_NO
    assert decision.entry_price_cents == 100 - 48
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.target_price < decision.stop_price
    assert decision.stop_price_cents is not None
    assert decision.target_price_cents is not None
    assert decision.target_price_cents >= decision.entry_price_cents
    assert decision.stop_price_cents <= decision.entry_price_cents


def test_holds_when_no_breakout():
    # Consolidation with no close beyond any level.
    prices = [100, 101, 102, 101, 100, 101, 102, 101, 100, 101, 100]
    bars = [_bar(i, p, volume=1.0) for i, p in enumerate(prices)]
    cfg = LevelBreakConfig(
        lookback_bars=2, level_tolerance_pct=0.05, min_touches=2, volume_lookback_bars=8
    )
    strat = LevelBreakStrategy(cfg)
    context = _context(bars)
    decision = strat.evaluate(context)
    assert decision.hold_reason in ("no_breakout", "volume_not_confirmed", "no_level_in_range")


def test_holds_on_missing_quotes():
    cfg = LevelBreakConfig(
        lookback_bars=2, level_tolerance_pct=0.01, min_touches=2, volume_lookback_bars=8
    )
    strat = LevelBreakStrategy(cfg)
    bars = _resistance_break_bars()
    context = _context(bars, yes_ask_cents=None)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "no_quotes"
