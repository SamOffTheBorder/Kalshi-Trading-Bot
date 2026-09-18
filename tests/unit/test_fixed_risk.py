"""Fixed-fractional (R-based) live sizing (tasks.md 5.1, design D3)."""

from __future__ import annotations

import pytest

from kalshi_bot.risk.fixed_risk import compute_r, size_fixed_risk


def test_compute_r_is_positive_distance():
    assert compute_r(entry_price=0.50, stop_price=0.40) == pytest.approx(0.10)
    assert compute_r(entry_price=0.40, stop_price=0.50) == pytest.approx(0.10)


def test_compute_r_rejects_zero_distance():
    with pytest.raises(ValueError):
        compute_r(entry_price=0.50, stop_price=0.50)


def test_size_fixed_risk_basic_r_based_sizing():
    # equity=1000, risk_pct=1% -> risk $10; R = 0.10/unit -> 100 units,
    # well under the 5% notional cap ($50 / $0.50 entry = 100 units too).
    size = size_fixed_risk(
        equity_usd=1000.0,
        entry_price=0.50,
        stop_price=0.40,
        risk_pct=0.01,
        max_position_pct=0.05,
    )
    assert size == 100


def test_size_fixed_risk_clamped_by_max_position_pct():
    # A very tight stop would justify a huge R-based size; the notional cap
    # must win regardless.
    size = size_fixed_risk(
        equity_usd=1000.0,
        entry_price=0.50,
        stop_price=0.499,
        risk_pct=0.01,
        max_position_pct=0.05,
    )
    # max notional size = (1000*0.05)/0.50 = 100
    assert size == 100


def test_size_fixed_risk_zero_on_nonpositive_equity():
    assert size_fixed_risk(
        equity_usd=0.0, entry_price=0.5, stop_price=0.4, risk_pct=0.01, max_position_pct=0.05
    ) == 0
    assert size_fixed_risk(
        equity_usd=-10.0, entry_price=0.5, stop_price=0.4, risk_pct=0.01, max_position_pct=0.05
    ) == 0


def test_size_fixed_risk_zero_on_degenerate_stop():
    assert size_fixed_risk(
        equity_usd=1000.0, entry_price=0.5, stop_price=0.5, risk_pct=0.01, max_position_pct=0.05
    ) == 0


def test_size_fixed_risk_rejects_out_of_band_risk_pct():
    with pytest.raises(ValueError):
        size_fixed_risk(
            equity_usd=1000.0, entry_price=0.5, stop_price=0.4, risk_pct=0.0, max_position_pct=0.05
        )
    with pytest.raises(ValueError):
        size_fixed_risk(
            equity_usd=1000.0, entry_price=0.5, stop_price=0.4, risk_pct=1.5, max_position_pct=0.05
        )


def test_size_fixed_risk_rejects_nonpositive_entry_price():
    with pytest.raises(ValueError):
        size_fixed_risk(
            equity_usd=1000.0,
            entry_price=0.0,
            stop_price=-0.1,
            risk_pct=0.01,
            max_position_pct=0.05,
        )


def test_size_fixed_risk_custom_unit_cost_for_perps():
    # Perp entry at $50,000/contract but stop distance ($500) measured in the
    # same dollar units; unit_cost defaults to entry_price when omitted, but
    # can diverge — verify the explicit override path is honored.
    size = size_fixed_risk(
        equity_usd=1000.0,
        entry_price=50_000.0,
        stop_price=49_500.0,
        risk_pct=0.01,
        max_position_pct=0.05,
        unit_cost=50_000.0,
    )
    # risk-based: 10 / 500 = 0.02 -> 0 whole units (equity too small for 1 contract)
    assert size == 0
