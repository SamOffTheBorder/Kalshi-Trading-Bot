"""KXBTC15M settlement-window features + baseline probability
(kxbtc15m-validation-rebuild §4.1). Known-answer style: synthetic BRTI
series with hand-computed expectations.
"""

from __future__ import annotations

import math

import pytest

from kalshi_bot.signals.settlement_window import (
    BRTIReading,
    build_features,
    settlement_probability,
    window_average,
)

OPEN = 1_784_000_000
CLOSE = OPEN + 900  # 15-minute window


def _series(start_ts: int, values: list[float], *, step: int = 1) -> list[BRTIReading]:
    return [BRTIReading(observed_at=start_ts + i * step, value=v) for i, v in enumerate(values)]


# --- window_average --------------------------------------------------------


def test_window_average_is_mean_over_trailing_60s():
    # 60 readings, one per second, ending exactly at OPEN.
    readings = _series(OPEN - 59, [100.0] * 60)
    assert window_average(readings, OPEN, window_seconds=60) == pytest.approx(100.0)


def test_window_average_excludes_readings_outside_the_interval():
    readings = _series(OPEN - 120, [1.0] * 60) + _series(OPEN - 59, [200.0] * 60)
    # only the second block is in (OPEN-60, OPEN]
    assert window_average(readings, OPEN, window_seconds=60) == pytest.approx(200.0)


def test_window_average_none_when_no_reading_in_interval():
    readings = _series(OPEN - 500, [100.0] * 10)
    assert window_average(readings, OPEN, window_seconds=60) is None


def test_window_average_respects_now_ts_usability_cutoff():
    readings = [
        BRTIReading(observed_at=OPEN - 30, value=100.0, available_at=OPEN - 30),
        BRTIReading(observed_at=OPEN - 10, value=200.0, available_at=OPEN + 5),  # not yet usable
    ]
    # at now_ts = OPEN the second reading is not available yet
    assert window_average(readings, OPEN, window_seconds=60, now_ts=OPEN) == pytest.approx(100.0)


# --- build_features ------------------------------------------------------


def test_reference_avg_is_fixed_open_window_average():
    readings = _series(OPEN - 59, [100.0] * 60) + _series(OPEN + 1, [101.0] * 300)
    f = build_features(readings, now_ts=OPEN + 300, open_ts=OPEN, close_ts=CLOSE)
    assert f.reference_avg == pytest.approx(100.0)
    assert f.seconds_remaining == 600
    assert f.fraction_elapsed == pytest.approx(300 / 900)


def test_drift_so_far_is_current_minus_reference():
    # open window at 100, then a flat run at 102 for the last 60s before now
    now = OPEN + 300
    readings = _series(OPEN - 59, [100.0] * 60) + _series(now - 59, [102.0] * 60)
    f = build_features(readings, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    assert f.reference_avg == pytest.approx(100.0)
    assert f.current_avg == pytest.approx(102.0)
    assert f.drift_so_far == pytest.approx(2.0)
    assert f.last_value == pytest.approx(102.0)


def test_features_use_only_readings_available_by_now_ts():
    now = OPEN + 300
    readings = [
        *_series(OPEN - 59, [100.0] * 60),
        BRTIReading(observed_at=now + 10, value=999.0, available_at=now + 10),  # future
    ]
    f = build_features(readings, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    assert f.last_value == pytest.approx(100.0)  # the future reading is ignored


def test_missing_open_window_gives_none_reference():
    readings = _series(OPEN + 1, [101.0] * 120)  # nothing before OPEN
    f = build_features(readings, now_ts=OPEN + 120, open_ts=OPEN, close_ts=CLOSE)
    assert f.reference_avg is None
    assert f.drift_so_far is None


# --- settlement_probability -------------------------------------------


def test_probability_none_when_drift_unknown():
    readings = _series(OPEN + 1, [101.0] * 60)
    f = build_features(readings, now_ts=OPEN + 60, open_ts=OPEN, close_ts=CLOSE)
    assert settlement_probability(f) is None


def test_probability_half_when_no_drift_and_symmetric():
    now = OPEN + 300
    readings = _series(OPEN - 59, [100.0] * 60) + _series(now - 59, [100.0] * 60)
    f = build_features(readings, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    # zero drift so far, zero assumed drift-per-sec -> P(Δ >= 0) = Phi(0) = 0.5
    p = settlement_probability(f, vol_per_sec=1e-4, drift_per_sec=0.0)
    assert p == pytest.approx(0.5)


def test_probability_matches_hand_computed_normal_cdf():
    now = OPEN + 300  # 600s remaining
    # reference 100, current 100.5 -> drift_so_far = 0.5
    readings = _series(OPEN - 59, [100.0] * 60) + _series(now - 59, [100.5] * 60)
    f = build_features(readings, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    assert f.drift_so_far == pytest.approx(0.5)

    sigma_1s = 2e-4  # log-return units
    level = 100.5
    t = 600.0
    price_std = level * sigma_1s * math.sqrt(t)
    expected = _normal_cdf(0.5 / price_std)
    p = settlement_probability(f, vol_per_sec=sigma_1s, drift_per_sec=0.0)
    assert p == pytest.approx(expected)
    assert p > 0.5  # positive drift so far -> favours YES


def test_probability_is_determined_at_zero_seconds_remaining():
    now = CLOSE
    up = _series(OPEN - 59, [100.0] * 60) + _series(now - 59, [101.0] * 60)
    down = _series(OPEN - 59, [100.0] * 60) + _series(now - 59, [99.0] * 60)
    f_up = build_features(up, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    f_down = build_features(down, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    assert settlement_probability(f_up) == 1.0
    assert settlement_probability(f_down) == 0.0


def test_probability_none_without_any_volatility_estimate():
    now = OPEN + 300
    # only two readings this window -> realized_vol_per_sec is None, and no override
    readings = [
        BRTIReading(OPEN - 30, 100.0),
        BRTIReading(now - 1, 100.4),
    ]
    f = build_features(readings, now_ts=now, open_ts=OPEN, close_ts=CLOSE)
    assert settlement_probability(f) is None


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
