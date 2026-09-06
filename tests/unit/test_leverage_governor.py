"""Leverage governor: ceiling + liquidation buffer (tasks.md 5.3, spec: perps-trading)."""

from __future__ import annotations

from kalshi_bot.risk.leverage_governor import (
    DEFAULT_LEVERAGE_CAP,
    HARD_LEVERAGE_CEILING,
    check_leverage_ceiling,
    check_liquidation_buffer,
    find_position_risk,
    liquidation_price_from_risk,
    max_notional_for_leverage_cap,
)

# --- leverage ceiling --------------------------------------------------------


def test_leverage_within_cap_is_allowed():
    result = check_leverage_ceiling(position_notional_usd=1500.0, equity_usd=1000.0)
    assert result.allowed is True
    assert result.implied_leverage == 1.5


def test_leverage_above_cap_is_rejected():
    result = check_leverage_ceiling(position_notional_usd=2500.0, equity_usd=1000.0)
    assert result.allowed is False
    assert result.implied_leverage == 2.5
    assert result.reason is not None
    assert "exceeds cap" in result.reason


def test_leverage_cap_cannot_exceed_hard_ceiling_even_if_configured_higher():
    # Someone passes leverage_cap=10 (misconfiguration); the hard ceiling
    # still governs — 3x notional on 1000 equity = 3000, and 3500 must fail.
    result = check_leverage_ceiling(
        position_notional_usd=3500.0, equity_usd=1000.0, leverage_cap=10.0
    )
    assert result.allowed is False
    assert result.reason is not None
    assert f"cap {HARD_LEVERAGE_CEILING:.2f}x" in result.reason


def test_leverage_exactly_at_cap_is_allowed():
    result = check_leverage_ceiling(position_notional_usd=2000.0, equity_usd=1000.0)
    assert result.allowed is True


def test_leverage_rejects_nonpositive_equity():
    result = check_leverage_ceiling(position_notional_usd=100.0, equity_usd=0.0)
    assert result.allowed is False
    assert result.implied_leverage is None


def test_max_notional_for_leverage_cap():
    assert max_notional_for_leverage_cap(equity_usd=1000.0) == 1000.0 * DEFAULT_LEVERAGE_CAP


def test_max_notional_clamped_by_hard_ceiling():
    assert max_notional_for_leverage_cap(
        equity_usd=1000.0, leverage_cap=10.0
    ) == 1000.0 * HARD_LEVERAGE_CEILING


def test_max_notional_zero_on_nonpositive_equity():
    assert max_notional_for_leverage_cap(equity_usd=0.0) == 0.0


# --- liquidation buffer ------------------------------------------------------


def test_liquidation_buffer_long_stop_safely_inside_is_allowed():
    result = check_liquidation_buffer(
        entry_price=50_000.0, stop_price=49_000.0, liquidation_price=45_000.0, side="long"
    )
    assert result.allowed is True
    assert result.stop_distance == 1000.0
    assert result.distance_to_liquidation == 5000.0


def test_liquidation_buffer_long_stop_beyond_liquidation_is_rejected():
    result = check_liquidation_buffer(
        entry_price=50_000.0, stop_price=44_000.0, liquidation_price=45_000.0, side="long"
    )
    assert result.allowed is False
    assert result.reason is not None
    assert "reaches or exceeds" in result.reason


def test_liquidation_buffer_long_stop_exactly_at_liquidation_is_rejected():
    result = check_liquidation_buffer(
        entry_price=50_000.0, stop_price=45_000.0, liquidation_price=45_000.0, side="long"
    )
    assert result.allowed is False


def test_liquidation_buffer_short_stop_safely_inside_is_allowed():
    result = check_liquidation_buffer(
        entry_price=50_000.0, stop_price=51_000.0, liquidation_price=55_000.0, side="short"
    )
    assert result.allowed is True


def test_liquidation_buffer_short_stop_beyond_liquidation_is_rejected():
    result = check_liquidation_buffer(
        entry_price=50_000.0, stop_price=56_000.0, liquidation_price=55_000.0, side="short"
    )
    assert result.allowed is False


# --- get_risk() response parsing --------------------------------------------


def test_find_position_risk_returns_matching_entry():
    risk_response = {
        "positions": [
            {"market_ticker": "KXBTCPERP", "estimated_liquidation_price": "45000.00"},
            {"market_ticker": "KXETHPERP", "estimated_liquidation_price": "3000.00"},
        ]
    }
    found = find_position_risk(risk_response, "KXETHPERP")
    assert found is not None
    assert found["estimated_liquidation_price"] == "3000.00"


def test_find_position_risk_returns_none_when_absent():
    assert find_position_risk({"positions": []}, "KXBTCPERP") is None


def test_liquidation_price_from_risk_parses_string():
    assert liquidation_price_from_risk({"estimated_liquidation_price": "45000.00"}) == 45000.0


def test_liquidation_price_from_risk_none_when_missing():
    assert liquidation_price_from_risk({"estimated_liquidation_price": None}) is None
    assert liquidation_price_from_risk({}) is None
