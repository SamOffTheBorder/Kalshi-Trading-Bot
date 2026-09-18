"""Settlement-aware KXBTC15M strategy + calibrators (kxbtc15m-validation-
rebuild §4.2/§4.3). Known-answer style throughout.
"""

from __future__ import annotations

import pytest

from kalshi_bot.signals.settlement_window import BRTIReading
from kalshi_bot.strategy.base import Action, StrategyContext
from kalshi_bot.strategy.settlement_prob import (
    IdentityCalibrator,
    IsotonicCalibrator,
    SettlementProbConfig,
    SettlementProbStrategy,
)

OPEN = 1_784_000_000
CLOSE = OPEN + 900


# --- calibrators ---------------------------------------------------------


def test_identity_calibrator_clamps_to_unit_interval():
    c = IdentityCalibrator()
    assert c.calibrate(0.5) == 0.5
    assert c.calibrate(-0.2) == 0.0
    assert c.calibrate(1.7) == 1.0
    assert c.version == "identity"


def test_isotonic_fit_returns_identity_below_min_points():
    cal = IsotonicCalibrator.fit([(0.5, 1.0), (0.6, 0.0)], version="fold1")
    assert isinstance(cal, IdentityCalibrator)
    assert "insufficient_data_n2" in cal.version


def test_isotonic_is_monotone_nondecreasing():
    # raw probs 0..1, outcomes noisy but trending up
    pairs = [
        (0.05, 0.0),
        (0.10, 0.0),
        (0.20, 0.0),
        (0.30, 1.0),
        (0.35, 0.0),
        (0.45, 1.0),
        (0.55, 0.0),
        (0.60, 1.0),
        (0.70, 1.0),
        (0.80, 1.0),
        (0.90, 1.0),
        (0.95, 1.0),
    ]
    cal = IsotonicCalibrator.fit(pairs, version="fold1")
    assert isinstance(cal, IsotonicCalibrator)
    grid = [i / 100 for i in range(101)]
    out = [cal.calibrate(x) for x in grid]
    assert out == sorted(out)  # non-decreasing everywhere
    assert all(0.0 <= v <= 1.0 for v in out)
    assert cal.version == "fold1"
    assert cal.n_fit == 12


def test_isotonic_corrects_a_systematically_overconfident_model():
    # model says ~0.9 but the bucket only wins ~0.5 of the time
    pairs = [(0.9, 1.0), (0.9, 0.0)] * 10  # 20 points, half win
    cal = IsotonicCalibrator.fit(pairs, version="fold1")
    assert isinstance(cal, IsotonicCalibrator)
    assert cal.calibrate(0.9) == pytest.approx(0.5, abs=1e-9)


def test_isotonic_clamps_outside_the_fitted_range():
    pairs = [(0.3, 0.0)] * 6 + [(0.7, 1.0)] * 6
    cal = IsotonicCalibrator.fit(pairs, version="fold1")
    assert isinstance(cal, IsotonicCalibrator)
    assert cal.calibrate(0.0) == cal.calibrate(0.3)  # clamped to left knot
    assert cal.calibrate(1.0) == cal.calibrate(0.7)  # clamped to right knot


# --- strategy pipeline -------------------------------------------------


def _brti(now_ts: int, *, ref: float, current: float) -> tuple[BRTIReading, ...]:
    """A synthetic BRTI series: 60 readings at `ref` ending at OPEN, then 60
    at `current` ending at now_ts, plus a couple of intermediate readings so
    realized_vol_per_sec is computable (>= 3 usable readings, and some
    price variation)."""
    readings: list[BRTIReading] = []
    for i in range(60):
        readings.append(BRTIReading(observed_at=OPEN - 59 + i, value=ref))
    # a few readings between OPEN and the current window with slight variation
    mid = (ref + current) / 2
    for k, v in enumerate((mid * 0.999, mid * 1.001, mid)):
        readings.append(BRTIReading(observed_at=OPEN + 60 + k * 30, value=v))
    for i in range(60):
        readings.append(BRTIReading(observed_at=now_ts - 59 + i, value=current))
    return tuple(readings)


def _ctx(
    *,
    now_ts: int,
    brti: tuple[BRTIReading, ...],
    yes_bid: int | None = 48,
    yes_ask: int | None = 52,
) -> StrategyContext:
    return StrategyContext(
        market_ticker="KXBTC15M-T",
        series_ticker="KXBTC15M",
        strike_type="greater",
        floor_strike=None,
        cap_strike=None,
        now_ts=now_ts,
        close_ts=CLOSE,
        yes_bid_cents=yes_bid,
        yes_ask_cents=yes_ask,
        spot=64_000.0,
        vol_annual=0.5,
        vol_source="test",
        brti_readings=brti,
    )


def test_holds_when_no_brti_readings():
    ctx = _ctx(now_ts=OPEN + 300, brti=())
    d = SettlementProbStrategy().evaluate(ctx)
    assert d.action == Action.HOLD
    assert d.hold_reason == "no_brti_readings"


def test_holds_outside_the_time_window():
    now = OPEN + 5  # only 5s elapsed -> below default min? actually 895s remaining > max
    ctx = _ctx(now_ts=now, brti=_brti(now, ref=64_000.0, current=64_000.0))
    d = SettlementProbStrategy().evaluate(ctx)
    assert d.action == Action.HOLD
    assert d.hold_reason == "outside_time_window"


def test_holds_when_edge_below_threshold_flat_market():
    now = OPEN + 300
    # no drift -> p ~ 0.5, priced at 52/48 -> negative edge after friction
    ctx = _ctx(now_ts=now, brti=_brti(now, ref=64_000.0, current=64_000.0))
    d = SettlementProbStrategy().evaluate(ctx)
    assert d.action == Action.HOLD
    assert d.hold_reason == "edge_below_threshold"


def test_enters_yes_on_strong_upward_drift_with_cheap_ask():
    now = OPEN + 300
    # big positive drift so far -> calibrated (identity) p well above 0.5,
    # and a cheap ask so the post-friction edge clears the threshold
    ctx = _ctx(
        now_ts=now,
        brti=_brti(now, ref=64_000.0, current=64_120.0),
        yes_bid=30,
        yes_ask=32,
    )
    d = SettlementProbStrategy().evaluate(ctx)
    assert d.action == Action.BUY_YES
    assert d.fair_probability is not None and d.fair_probability > 0.5
    assert d.entry_price_cents == 32
    assert d.min_entry_price_cents == 28 and d.max_entry_price_cents == 36
    assert d.fee_adjusted_edge is not None and d.fee_adjusted_edge > 0.03
    assert d.model_meta["model"] == "settlement_prob_baseline"
    assert d.model_meta["calibrator_version"] == "identity"
    assert d.model_meta["raw_probability"] == pytest.approx(d.model_meta["calibrated_probability"])


def test_enters_no_on_strong_downward_drift_with_cheap_no_price():
    now = OPEN + 300
    # negative drift -> p(YES) well below 0.5 -> p(NO) high; yes_bid high so
    # NO price = 100 - yes_bid is cheap
    ctx = _ctx(
        now_ts=now,
        brti=_brti(now, ref=64_000.0, current=63_880.0),
        yes_bid=68,
        yes_ask=72,
    )
    d = SettlementProbStrategy().evaluate(ctx)
    assert d.action == Action.BUY_NO
    assert d.entry_price_cents == 32  # 100 - 68
    assert d.fair_probability is not None and d.fair_probability > 0.5  # P(NO wins)


def test_injected_calibrator_version_and_value_flow_through():
    now = OPEN + 300
    # a calibrator that squashes everything to exactly 0.5 -> no edge -> HOLD,
    # but its version must still be recorded on the HOLD? No: HOLD carries no
    # model_meta. Use a calibrator that pushes p up instead.
    class Boost:
        version = "fold3-boost"

        def calibrate(self, raw_p: float) -> float:
            return min(1.0, raw_p + 0.25)

    ctx = _ctx(
        now_ts=now,
        brti=_brti(now, ref=64_000.0, current=64_010.0),
        yes_bid=30,
        yes_ask=32,
    )
    d = SettlementProbStrategy(calibrator=Boost()).evaluate(ctx)
    assert d.action == Action.BUY_YES
    assert d.model_meta["calibrator_version"] == "fold3-boost"
    assert d.model_meta["calibrated_probability"] == pytest.approx(
        min(1.0, d.model_meta["raw_probability"] + 0.25)
    )


def test_config_min_edge_gates_entry():
    now = OPEN + 300
    brti = _brti(now, ref=64_000.0, current=64_030.0)
    cheap = _ctx(now_ts=now, brti=brti, yes_bid=30, yes_ask=32)
    # a punishing min_edge should turn the same setup into a HOLD
    strict = SettlementProbStrategy(SettlementProbConfig(min_edge=0.90))
    assert strict.evaluate(cheap).action == Action.HOLD
