"""Deterministic swing-level detection (tasks.md 6.1/6.2/6.5, design D2).
Known-answer tests: synthetic bars -> exact expected levels."""

from __future__ import annotations

import pytest

from kalshi_bot.strategy.levels import (
    SpotBar,
    compute_vwap,
    find_swing_levels,
    level_is_respected,
    spot_r_to_contract_cents,
)


def _bar(ts: int, price: float, *, high=None, low=None, volume=0.0) -> SpotBar:
    return SpotBar(
        ts=ts,
        open=price,
        high=high if high is not None else price,
        low=low if low is not None else price,
        close=price,
        volume=volume,
    )


def test_find_swing_levels_detects_a_single_confirmed_high():
    # A clean V-up-then-down shape: bar index 5 is the highest high in any
    # symmetric window, and its neighbors approach close enough to count as
    # additional touches.
    prices = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    levels = find_swing_levels(bars, lookback=3, tolerance_pct=0.01, min_touches=1)
    highs = [lvl for lvl in levels if lvl.kind == "high"]
    assert any(lvl.price == pytest.approx(110) for lvl in highs)


def test_find_swing_levels_detects_a_single_confirmed_low():
    prices = [110, 108, 106, 104, 100, 104, 106, 108, 110]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    levels = find_swing_levels(bars, lookback=3, tolerance_pct=0.01, min_touches=1)
    lows = [lvl for lvl in levels if lvl.kind == "low"]
    assert any(lvl.price == pytest.approx(100) for lvl in lows)


def test_find_swing_levels_requires_min_touches():
    # A single, isolated swing high with no nearby second touch must be
    # dropped when min_touches=2.
    prices = [100, 101, 102, 110, 102, 101, 100, 99, 98, 97, 96]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    levels = find_swing_levels(bars, lookback=3, tolerance_pct=0.001, min_touches=2)
    assert not any(lvl.price == pytest.approx(110) for lvl in levels)


def test_find_swing_levels_merges_nearby_touches_into_one_level():
    # Two swing highs at 110 and 110.5 (0.45% apart) should merge under a 1%
    # tolerance into a single 2-touch level.
    prices = [100, 105, 110, 105, 100, 105, 110.5, 105, 100]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    levels = find_swing_levels(bars, lookback=2, tolerance_pct=0.01, min_touches=2)
    highs = [lvl for lvl in levels if lvl.kind == "high"]
    assert len(highs) == 1
    assert highs[0].touches == 2
    assert highs[0].price == pytest.approx((110 + 110.5) / 2)


def test_find_swing_levels_is_deterministic():
    prices = [100, 103, 107, 103, 100, 96, 92, 96, 100]
    bars = [_bar(i, p) for i, p in enumerate(prices)]
    first = find_swing_levels(bars, lookback=2, tolerance_pct=0.02, min_touches=1)
    second = find_swing_levels(bars, lookback=2, tolerance_pct=0.02, min_touches=1)
    assert first == second


def test_find_swing_levels_rejects_bad_params():
    bars = [_bar(0, 100)]
    with pytest.raises(ValueError):
        find_swing_levels(bars, lookback=0, tolerance_pct=0.01)
    with pytest.raises(ValueError):
        find_swing_levels(bars, lookback=1, tolerance_pct=0.0)
    with pytest.raises(ValueError):
        find_swing_levels(bars, lookback=1, tolerance_pct=0.01, min_touches=0)


def test_compute_vwap_weights_by_volume():
    bars = [
        _bar(0, 100, volume=1.0),
        _bar(1, 200, volume=3.0),
    ]
    # (100*1 + 200*3) / 4 = 175
    assert compute_vwap(bars) == pytest.approx(175.0)


def test_compute_vwap_none_when_no_volume():
    bars = [_bar(0, 100, volume=0.0), _bar(1, 200, volume=0.0)]
    assert compute_vwap(bars) is None


def test_level_is_respected_support_holds():
    from kalshi_bot.strategy.levels import SwingLevel

    level = SwingLevel(price=100.0, kind="low", touches=2, first_touch_ts=0, last_touch_ts=1)
    # Price dips to 99.5 (within 1% band) but closes back above 100 -> respected.
    assert level_is_respected(level, approach_price=99.5, close_price=100.2, tolerance_pct=0.01)


def test_level_is_respected_support_breaks_on_close_through():
    from kalshi_bot.strategy.levels import SwingLevel

    level = SwingLevel(price=100.0, kind="low", touches=2, first_touch_ts=0, last_touch_ts=1)
    assert not level_is_respected(
        level, approach_price=99.5, close_price=98.0, tolerance_pct=0.01
    )


def test_level_is_respected_resistance_breaks_on_close_through():
    from kalshi_bot.strategy.levels import SwingLevel

    level = SwingLevel(price=100.0, kind="high", touches=2, first_touch_ts=0, last_touch_ts=1)
    assert not level_is_respected(
        level, approach_price=100.5, close_price=101.0, tolerance_pct=0.01
    )


def test_level_is_respected_false_when_price_never_approached():
    from kalshi_bot.strategy.levels import SwingLevel

    level = SwingLevel(price=100.0, kind="low", touches=2, first_touch_ts=0, last_touch_ts=1)
    assert not level_is_respected(
        level, approach_price=110.0, close_price=110.0, tolerance_pct=0.01
    )


# --- spot_r_to_contract_cents -------------------------------------------------


def test_spot_r_to_contract_cents_yes_side_target_above_entry():
    # +4% spot move for a YES position -> cents move in the SAME direction.
    cents = spot_r_to_contract_cents(100.0, 104.0, 50, side="yes")
    assert cents == 52  # 50 + round(0.04 * 50)


def test_spot_r_to_contract_cents_yes_side_stop_below_entry():
    cents = spot_r_to_contract_cents(100.0, 96.0, 50, side="yes")
    assert cents == 48


def test_spot_r_to_contract_cents_no_side_flips_sign():
    # +4% spot move is BEARISH for a NO position's own contract price
    # (NO price = 100 - yes_price), so the cents delta flips.
    cents_yes = spot_r_to_contract_cents(100.0, 104.0, 50, side="yes")
    cents_no = spot_r_to_contract_cents(100.0, 104.0, 50, side="no")
    assert cents_no == 50 - (cents_yes - 50)


def test_spot_r_to_contract_cents_clamped_to_valid_range():
    assert spot_r_to_contract_cents(100.0, 200.0, 95, side="yes") == 99
    assert spot_r_to_contract_cents(100.0, 1.0, 5, side="yes") == 1


def test_spot_r_to_contract_cents_rejects_nonpositive_entry():
    with pytest.raises(ValueError):
        spot_r_to_contract_cents(0.0, 1.0, 50, side="yes")


def test_spot_r_to_contract_cents_zero_distance_is_unchanged():
    assert spot_r_to_contract_cents(100.0, 100.0, 50, side="yes") == 50
    assert spot_r_to_contract_cents(100.0, 100.0, 50, side="no") == 50
