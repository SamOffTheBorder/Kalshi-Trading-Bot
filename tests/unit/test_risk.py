"""Kelly sizing edge cases and drawdown-guard state transitions."""

import pytest

from kalshi_bot.risk.drawdown_guard import DrawdownGuard, GuardState
from kalshi_bot.risk.kelly import binary_kelly_fraction, size_binary_position

# --- Kelly formula ------------------------------------------------------------


def test_kelly_reduces_to_classic_form_without_fee():
    """fee=0: f* = (p - c) / (1 - c). p=0.6, c=0.5 -> 0.2."""
    assert binary_kelly_fraction(0.6, 0.5, fee_rate=0.0) == pytest.approx(0.2)


def test_kelly_zero_at_no_edge():
    assert binary_kelly_fraction(0.5, 0.5, fee_rate=0.0) == 0.0


def test_kelly_zero_on_negative_edge():
    assert binary_kelly_fraction(0.4, 0.5) == 0.0


def test_fee_shrinks_kelly():
    with_fee = binary_kelly_fraction(0.6, 0.5, fee_rate=0.07)
    without = binary_kelly_fraction(0.6, 0.5, fee_rate=0.0)
    assert 0 < with_fee < without


def test_fee_can_zero_out_marginal_edge():
    """p barely above cost: positive Kelly without fee, zero with."""
    assert binary_kelly_fraction(0.51, 0.50, fee_rate=0.0) > 0
    assert binary_kelly_fraction(0.51, 0.50, fee_rate=0.07) == 0.0


def test_kelly_input_validation():
    with pytest.raises(ValueError):
        binary_kelly_fraction(1.5, 0.5)
    with pytest.raises(ValueError):
        binary_kelly_fraction(0.5, 0.0)
    with pytest.raises(ValueError):
        binary_kelly_fraction(0.5, 1.0)


# --- position sizing with the hard cap -------------------------------------------


def test_cap_clamps_kelly_output():
    """Spec scenario: Kelly says 12%+, cap says 5% -> position is 5%.

    p=0.9 at 30¢ is a monster edge; quarter-Kelly of it still exceeds 5%.
    """
    contracts = size_binary_position(
        p_win=0.9,
        cost_cents=30,
        bankroll_usd=130.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
    )
    assert contracts == int((130.0 * 0.05) // 0.30)  # exactly the cap
    # and the uncapped Kelly budget would have been bigger:
    assert 0.25 * binary_kelly_fraction(0.9, 0.30) > 0.05


def test_zero_contracts_at_or_below_fee_adjusted_breakeven():
    """Spec scenario: p at/below fee-adjusted cost -> zero contracts."""
    assert (
        size_binary_position(
            p_win=0.50,
            cost_cents=50,
            bankroll_usd=130.0,
            kelly_fraction=0.25,
            max_position_pct=0.05,
        )
        == 0
    )


def test_zero_on_dust_bankroll():
    assert (
        size_binary_position(
            p_win=0.7,
            cost_cents=45,
            bankroll_usd=0.30,  # can't afford one 45¢ contract at capped size
            kelly_fraction=0.25,
            max_position_pct=0.05,
        )
        == 0
    )


def test_zero_on_nonpositive_bankroll():
    assert (
        size_binary_position(
            p_win=0.7,
            cost_cents=45,
            bankroll_usd=0.0,
            kelly_fraction=0.25,
            max_position_pct=0.05,
        )
        == 0
    )


def test_whole_contracts_floor():
    contracts = size_binary_position(
        p_win=0.65,
        cost_cents=40,
        bankroll_usd=130.0,
        kelly_fraction=0.25,
        max_position_pct=0.05,
    )
    assert isinstance(contracts, int)
    assert contracts * 0.40 <= 130.0 * 0.05 + 1e-9


# --- drawdown guard ------------------------------------------------------------------


def _guard() -> DrawdownGuard:
    return DrawdownGuard(pause_pct=0.25, halt_pct=0.40, initial_equity=130.0)


def test_normal_below_pause():
    g = _guard()
    assert g.update(120.0) == GuardState.NORMAL
    assert g.allows_new_entries()


def test_pause_at_threshold_blocks_entries_only():
    g = _guard()
    state = g.update(130.0 * 0.75)  # exactly 25% down
    assert state == GuardState.PAUSED
    assert not g.allows_new_entries()


def test_pause_recovers_to_normal():
    g = _guard()
    g.update(95.0)  # ~27% down -> PAUSED
    assert g.state == GuardState.PAUSED
    assert g.update(125.0) == GuardState.NORMAL


def test_halt_at_threshold():
    g = _guard()
    assert g.update(130.0 * 0.60) == GuardState.HALTED


def test_halt_is_sticky_until_reset():
    g = _guard()
    g.update(70.0)  # ~46% down -> HALTED
    assert g.update(129.0) == GuardState.HALTED  # recovery doesn't clear it
    g.reset(approved_by="test-human")
    assert g.state == GuardState.NORMAL


def test_peak_tracks_new_highs():
    g = _guard()
    g.update(200.0)  # new peak
    assert g.peak_equity == 200.0
    assert g.update(155.0) == GuardState.NORMAL  # 22.5% off new peak
    assert g.update(149.0) == GuardState.PAUSED  # 25.5% off new peak
    assert g.drawdown == pytest.approx(1 - 149.0 / 200.0)


def test_threshold_ordering_enforced():
    with pytest.raises(ValueError):
        DrawdownGuard(pause_pct=0.40, halt_pct=0.25, initial_equity=100.0)
