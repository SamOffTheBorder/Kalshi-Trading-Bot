"""Trend-scalp strategy: known-answer tests, synthetic bars -> exact
expected decisions (tasks.md 6.1/6.5)."""

from __future__ import annotations

import dataclasses

import pytest

from kalshi_bot.strategy.base import Action, StrategyContext
from kalshi_bot.strategy.levels import SpotBar
from kalshi_bot.strategy.trend_scalp import TrendScalpConfig, TrendScalpStrategy


def _bar(ts: int, price: float, *, high=None, low=None) -> SpotBar:
    return SpotBar(
        ts=ts,
        open=price,
        high=high if high is not None else price,
        low=low if low is not None else price,
        close=price,
        volume=1.0,
    )


def _uptrend_pullback_bars() -> list[SpotBar]:
    # Rally to 110 (a confirmed swing high isn't needed for an uptrend
    # pullback — we need a confirmed LOW), pull back to a support around
    # 100 that was touched twice, then the latest bar sits right at that
    # support and closes back above it (respected).
    prices = [95, 97, 100, 103, 106, 108, 104, 100.2, 103, 106, 100.3]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    # Make the two touches of ~100 actual local lows by construction: index
    # 2 (100) and index 7 (100.2) are each lower than their neighbors.
    return bars


def _context(
    bars: list[SpotBar], trend_zscore: float | None, **overrides: object
) -> StrategyContext:
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
        trend_zscore=trend_zscore,
        spot_bars=tuple(bars),
    )
    return dataclasses.replace(base, **overrides)


def test_holds_when_too_close_to_expiry():
    strat = TrendScalpStrategy()
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=1.0, now_ts=1000, close_ts=1000 + 60)
    decision = strat.evaluate(context)
    assert decision.action == Action.HOLD
    assert decision.hold_reason == "too_close_to_expiry"


def test_holds_when_no_trend_signal():
    strat = TrendScalpStrategy()
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=None)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "no_trend_signal"


def test_holds_when_trend_too_weak():
    strat = TrendScalpStrategy(TrendScalpConfig(min_trend_zscore=0.5))
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=0.1)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "trend_too_weak"


def test_holds_on_insufficient_bar_history():
    strat = TrendScalpStrategy()
    context = _context([_bar(0, 100)], trend_zscore=1.0)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "insufficient_bar_history"


def test_uptrend_pullback_to_respected_support_enters_buy_yes():
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.01, min_touches=2)
    )
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=1.0)
    decision = strat.evaluate(context)
    assert decision.action == Action.BUY_YES
    assert decision.entry_price_cents == 52
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.target_price > decision.stop_price


def test_uptrend_pullback_populates_contract_cents_fields():
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.01, min_touches=2)
    )
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=1.0)
    decision = strat.evaluate(context)
    assert decision.stop_price_cents is not None
    assert decision.target_price_cents is not None
    # BUY_YES: contract cents move the SAME direction as spot, so target
    # (above entry in spot terms) should be >= entry, stop <= entry.
    assert decision.target_price_cents >= decision.entry_price_cents
    assert decision.stop_price_cents <= decision.entry_price_cents


def test_downtrend_pullback_populates_contract_cents_fields_flipped():
    prices = [105, 103, 100, 97, 94, 92, 96, 99.8, 97, 94, 99.7]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.01, min_touches=2)
    )
    context = _context(bars, trend_zscore=-1.0)
    decision = strat.evaluate(context)
    assert decision.stop_price_cents is not None
    assert decision.target_price_cents is not None
    # BUY_NO: spot falling further (the target direction) is BULLISH for
    # the NO contract's own price, so target cents >= entry, stop <= entry
    # — same ordering as YES despite the opposite spot direction, because
    # the sign flip in spot_r_to_contract_cents is designed to keep
    # "toward target" meaning "cents increase" regardless of side.
    assert decision.target_price_cents >= decision.entry_price_cents
    assert decision.stop_price_cents <= decision.entry_price_cents


def test_target_is_r_multiple_beyond_entry_on_uptrend():
    cfg = TrendScalpConfig(
        lookback_bars=2, level_tolerance_pct=0.01, min_touches=2, r_multiple_target=2.0
    )
    strat = TrendScalpStrategy(cfg)
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=1.0)
    decision = strat.evaluate(context)
    assert decision.stop_price is not None
    assert decision.target_price is not None
    entry = bars[-1].close
    r = abs(entry - decision.stop_price)
    assert decision.target_price == pytest.approx(entry + 2.0 * r)


def test_downtrend_pullback_to_respected_resistance_enters_buy_no():
    prices = [105, 103, 100, 97, 94, 92, 96, 99.8, 97, 94, 99.7]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.01, min_touches=2)
    )
    context = _context(bars, trend_zscore=-1.0)
    decision = strat.evaluate(context)
    assert decision.action == Action.BUY_NO
    assert decision.entry_price_cents == 100 - 48
    assert decision.stop_price is not None
    assert decision.target_price is not None
    assert decision.target_price < decision.stop_price


def test_holds_when_no_level_in_range():
    # Monotonically rising with no clear consolidation -> no confirmed low.
    prices = [float(90 + i) for i in range(20)]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.001, min_touches=3)
    )
    context = _context(bars, trend_zscore=1.0)
    decision = strat.evaluate(context)
    assert decision.hold_reason in ("no_level_in_range", "level_not_respected")


def test_holds_on_missing_quotes():
    strat = TrendScalpStrategy(
        TrendScalpConfig(lookback_bars=2, level_tolerance_pct=0.01, min_touches=2)
    )
    bars = _uptrend_pullback_bars()
    context = _context(bars, trend_zscore=1.0, yes_ask_cents=None)
    decision = strat.evaluate(context)
    assert decision.hold_reason == "no_quotes"
