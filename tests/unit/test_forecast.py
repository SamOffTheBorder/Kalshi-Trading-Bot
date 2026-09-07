"""Short-horizon forecast signal (tasks.md 7.2).

The real backend (Chronos-Bolt) is not wired yet; `StubForecaster` is a
deterministic naive-drift baseline with fail-SAFE semantics (a forecast that
cannot be produced returns a neutral no-opinion row, never raises). These
tests pin that contract and the stub's arithmetic against hand-computed
values.
"""

from __future__ import annotations

from math import exp, log

import pytest

from kalshi_bot.ai.forecast import (
    ForecastSignal,
    StubForecaster,
    to_forecast_record,
)
from kalshi_bot.strategy.levels import SpotBar

BAR_S = 60  # 1-minute input bars


def _bars(
    closes: list[float], *, start_ts: int = 1_752_000_000, step: int = BAR_S
) -> list[SpotBar]:
    return [
        SpotBar(ts=start_ts + i * step, open=c, high=c, low=c, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


def test_flat_history_forecasts_no_move():
    bars = _bars([100.0] * 12)
    sig = StubForecaster().forecast(bars, symbol="BTC-USD", horizon_minutes=15)
    assert sig.available
    assert sig.reason == "ok"
    assert sig.median_price == pytest.approx(100.0)
    assert sig.expected_return == pytest.approx(0.0)
    # zero variance => zero-width interval
    assert sig.low_price == pytest.approx(100.0)
    assert sig.high_price == pytest.approx(100.0)


def test_constant_drift_is_projected_forward():
    # +0.1% per bar, 10 bars of history, 15 one-minute steps ahead.
    r = 0.001
    closes = [100.0 * exp(r * i) for i in range(11)]
    bars = _bars(closes)
    sig = StubForecaster(interval_k=1.28).forecast(bars, symbol="BTC-USD", horizon_minutes=15)

    # mean per-bar log return is exactly r; horizon is 15 min / 1 min = 15 steps.
    expected_median = closes[-1] * exp(r * 15)
    assert sig.median_price == pytest.approx(expected_median)
    assert sig.expected_return == pytest.approx(expected_median / closes[-1] - 1.0)
    # constant geometric drift => zero return variance => zero band
    assert sig.low_price == pytest.approx(expected_median)
    assert sig.high_price == pytest.approx(expected_median)


def test_interval_widens_with_volatility_and_horizon():
    closes = [100.0, 101.0, 100.0, 101.5, 99.5, 101.0, 100.0, 102.0, 99.0, 101.0, 100.0]
    bars = _bars(closes)
    fc = StubForecaster(interval_k=1.28)
    short = fc.forecast(bars, symbol="BTC-USD", horizon_minutes=5)
    long = fc.forecast(bars, symbol="BTC-USD", horizon_minutes=30)
    short_width = short.high_price - short.low_price
    long_width = long.high_price - long.low_price
    assert long_width > short_width > 0


def test_band_matches_hand_computed_value():
    closes = [100.0, 102.0, 100.0, 102.0, 100.0, 102.0, 100.0, 102.0, 100.0, 102.0]
    bars = _bars(closes)
    k = 1.28
    sig = StubForecaster(interval_k=k).forecast(bars, symbol="BTC-USD", horizon_minutes=15)

    rets = [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean_ret = sum(rets) / len(rets)
    var = sum((x - mean_ret) ** 2 for x in rets) / len(rets)
    stdev = var**0.5
    steps = 15 * 60 / BAR_S
    band = k * stdev * steps**0.5
    last = closes[-1]
    assert sig.median_price == pytest.approx(last * exp(mean_ret * steps))
    assert sig.low_price == pytest.approx(last * exp(mean_ret * steps - band))
    assert sig.high_price == pytest.approx(last * exp(mean_ret * steps + band))


def test_insufficient_history_returns_neutral():
    bars = _bars([100.0, 101.0, 102.0])  # < default min 8
    sig = StubForecaster().forecast(bars, symbol="BTC-USD", horizon_minutes=15)
    assert not sig.available
    assert sig.reason == "insufficient_history"
    assert sig.median_price is None
    assert sig.expected_return is None
    assert sig.last_price == 102.0  # still reported
    assert sig.asof_ts == bars[-1].ts


def test_empty_history_returns_neutral_without_raising():
    sig = StubForecaster().forecast([], symbol="BTC-USD", horizon_minutes=15)
    assert not sig.available
    assert sig.reason == "insufficient_history"
    assert sig.last_price == 0.0


def test_non_positive_price_returns_neutral():
    bars = _bars([100.0] * 7 + [0.0])
    sig = StubForecaster().forecast(bars, symbol="BTC-USD", horizon_minutes=15)
    assert not sig.available
    assert sig.reason == "non_positive_price"


def test_horizon_shorter_than_one_bar_still_projects_one_step():
    r = 0.002
    closes = [100.0 * exp(r * i) for i in range(11)]
    bars = _bars(closes, step=600)  # 10-minute bars
    sig = StubForecaster().forecast(bars, symbol="BTC-USD", horizon_minutes=1)
    # 1 min / 10 min < 1 step, clamped to 1 step.
    assert sig.median_price == pytest.approx(closes[-1] * exp(r * 1))


def test_latency_is_measured_on_every_path():
    ok = StubForecaster().forecast(_bars([100.0] * 10), symbol="BTC-USD", horizon_minutes=15)
    neutral = StubForecaster().forecast(_bars([100.0]), symbol="BTC-USD", horizon_minutes=15)
    assert ok.latency_ms is not None and ok.latency_ms >= 0
    assert neutral.latency_ms is not None and neutral.latency_ms >= 0


def test_neutral_factory_shape():
    sig = ForecastSignal.neutral(
        symbol="BTC-USD",
        asof_ts=123,
        horizon_minutes=15,
        last_price=64000.0,
        reason="backend_error:boom",
    )
    assert sig.available is False
    assert (sig.median_price, sig.low_price, sig.high_price, sig.expected_return) == (
        None,
        None,
        None,
        None,
    )
    assert sig.reason == "backend_error:boom"


def test_to_forecast_record_maps_available_signal():
    sig = StubForecaster().forecast(_bars([100.0, 101.0] * 5), symbol="BTC-USD", horizon_minutes=15)
    rec = to_forecast_record(sig, backend="stub", signal_id=7)
    assert rec.signal_id == 7
    assert rec.backend == "stub"
    assert rec.symbol == "BTC-USD"
    assert rec.available is True
    assert rec.median_price == pytest.approx(sig.median_price)
    assert rec.expected_return == pytest.approx(sig.expected_return)
    assert rec.latency_ms == sig.latency_ms


def test_to_forecast_record_maps_neutral_signal_without_signal_id():
    sig = ForecastSignal.neutral(
        symbol="BTC-USD",
        asof_ts=123,
        horizon_minutes=15,
        last_price=64000.0,
        reason="insufficient_history",
    )
    rec = to_forecast_record(sig, backend="stub")
    assert rec.signal_id is None
    assert rec.available is False
    assert rec.median_price is None
    assert rec.reason == "insufficient_history"


def test_bar_spacing_from_median_gap_is_robust_to_one_odd_gap():
    # 1-minute bars with a single 1-hour gap in the middle; median gap is
    # still 60s, so the horizon->steps conversion is unaffected.
    closes = [100.0] * 12
    bars = _bars(closes)
    bad = list(bars)
    bad[6] = SpotBar(
        ts=bad[5].ts + 3600, open=100.0, high=100.0, low=100.0, close=100.0, volume=1.0
    )
    for j in range(7, len(bad)):
        bad[j] = SpotBar(
            ts=bad[6].ts + (j - 6) * BAR_S,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1.0,
        )
    sig = StubForecaster().forecast(bad, symbol="BTC-USD", horizon_minutes=15)
    assert sig.available
    assert sig.median_price == pytest.approx(100.0)
