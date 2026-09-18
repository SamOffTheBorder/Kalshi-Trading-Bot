"""Known-answer tests for the bounded settlement-aware reversion candidate."""

from __future__ import annotations

import pytest

from kalshi_bot.signals.mean_reversion import build_mean_reversion_features
from kalshi_bot.signals.settlement_window import BRTIReading
from kalshi_bot.strategy.base import Action, StrategyContext
from kalshi_bot.strategy.mean_reversion import (
    MeanReversionConfig,
    MeanReversionSettlementStrategy,
)

OPEN = 1_784_000_000
CLOSE = OPEN + 900
NOW = OPEN + 300


def _readings(*, last: float) -> tuple[BRTIReading, ...]:
    readings = [BRTIReading(observed_at=OPEN - 59 + i, value=100_000.0) for i in range(60)]
    readings.extend(
        BRTIReading(
            observed_at=NOW - 179 + i,
            value=100_000.0 + (2.0 if i % 2 else -2.0),
        )
        for i in range(179)
    )
    readings.append(BRTIReading(observed_at=NOW, value=last))
    return tuple(readings)


def _context(readings: tuple[BRTIReading, ...], *, yes_bid: int = 68) -> StrategyContext:
    return StrategyContext(
        market_ticker="KXBTC15M-T",
        series_ticker="KXBTC15M",
        strike_type="greater",
        floor_strike=None,
        cap_strike=None,
        now_ts=NOW,
        close_ts=CLOSE,
        yes_bid_cents=yes_bid,
        yes_ask_cents=72,
        spot=100_000.0,
        vol_annual=0.5,
        vol_source="test",
        brti_readings=readings,
    )


def test_displacement_excludes_the_latest_reading_from_its_reference_window():
    features = build_mean_reversion_features(_readings(last=100_020.0), now_ts=NOW)
    assert features.sample_count == 179
    assert features.trailing_mean == pytest.approx(100_000.0, abs=0.1)
    assert features.displacement == pytest.approx(20.0, abs=0.1)
    assert features.zscore is not None and features.zscore > 2.0


def test_future_or_delayed_readings_cannot_affect_the_feature():
    readings = [*_readings(last=100_020.0)]
    readings.append(BRTIReading(observed_at=NOW + 1, available_at=NOW, value=999_999.0))
    readings.append(BRTIReading(observed_at=NOW, available_at=NOW + 1, value=999_999.0))
    features = build_mean_reversion_features(readings, now_ts=NOW)
    assert features.last_value == 100_020.0


def test_strong_upward_displacement_creates_a_no_candidate_from_executable_quote():
    strategy = MeanReversionSettlementStrategy(MeanReversionConfig(max_trend_zscore=100.0))
    decision = strategy.evaluate(_context(_readings(last=100_020.0)))
    assert decision.action == Action.BUY_NO
    assert decision.strategy_name == "settlement_mean_reversion"
    assert decision.model_meta["model"] == "settlement_prob_mean_reversion"
    assert decision.model_meta["mean_reversion"]["reversion_drift_per_sec"] < 0


def test_candidate_holds_when_displacement_is_not_unusual():
    decision = MeanReversionSettlementStrategy().evaluate(_context(_readings(last=100_002.0)))
    assert decision.action == Action.HOLD
    assert decision.hold_reason == "mean_reversion_signal_too_weak"


def test_candidate_refuses_to_fade_a_strong_trend_regime():
    readings = [BRTIReading(observed_at=OPEN - 59 + i, value=100_000.0) for i in range(60)]
    readings.extend(
        BRTIReading(observed_at=NOW - 179 + i, value=100_000.0 + 0.2 * i) for i in range(179)
    )
    readings.append(BRTIReading(observed_at=NOW, value=100_050.0))
    decision = MeanReversionSettlementStrategy().evaluate(_context(tuple(readings)))
    assert decision.action == Action.HOLD
    assert decision.hold_reason == "mean_reversion_trend_regime"
