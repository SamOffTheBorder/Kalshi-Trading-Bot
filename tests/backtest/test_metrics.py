"""Backtest metrics beyond win rate/PnL (tasks.md 8.2): trade concentration,
max consecutive losses, R-multiple distribution."""

from __future__ import annotations

import pytest

from kalshi_bot.backtest.metrics import (
    compute_segment_metrics,
    flat_sizing_net_pnl_usd,
    max_consecutive_losses,
    r_multiples,
    top_n_concentration,
)
from kalshi_bot.execution.backtest_broker import Settlement
from kalshi_bot.signals.fees import entry_fee_dollars


def _settlement(
    *, ts: int, won: bool, entry_price_cents: int = 50, quantity: int = 10, gross: float, net: float
) -> Settlement:
    return Settlement(
        market_ticker=f"M-{ts}",
        side="yes",
        quantity=quantity,
        entry_price_cents=entry_price_cents,
        entry_ts=ts,
        won=won,
        gross_pnl_usd=gross,
        fee_usd=gross - net if won else 0.2,
        net_pnl_usd=net,
        settled_ts=ts + 900,
    )


# --- top_n_concentration -------------------------------------------------------


def test_top10_concentration_below_hundred_percent_when_evenly_distributed():
    settlements = [_settlement(ts=i, won=True, gross=1.0, net=0.9) for i in range(15)]
    conc = top_n_concentration(settlements, n=10)
    assert conc == pytest.approx(10 / 15)


def test_top10_concentration_over_hundred_percent_when_top_trades_dominate():
    # Phase 1's run #8 scenario: the top 10 winners alone exceed the
    # strategy's TOTAL NET profit, because the rest of the book (small
    # winners + losers) is a net drag once fees/losses are netted in.
    big_winners = [_settlement(ts=i, won=True, gross=10.0, net=9.5) for i in range(10)]
    small_losers = [_settlement(ts=100 + i, won=False, gross=-5.0, net=-5.2) for i in range(5)]
    settlements = big_winners + small_losers
    conc = top_n_concentration(settlements, n=10)
    assert conc is not None
    assert conc > 1.0


def test_top10_concentration_none_with_fewer_than_n_trades():
    settlements = [_settlement(ts=i, won=True, gross=1.0, net=0.9) for i in range(5)]
    assert top_n_concentration(settlements, n=10) is None


def test_top10_concentration_none_when_no_profit_at_all():
    settlements = [_settlement(ts=i, won=False, gross=-1.0, net=-1.2) for i in range(15)]
    assert top_n_concentration(settlements, n=10) is None


# --- max_consecutive_losses ----------------------------------------------------


def test_max_consecutive_losses_counts_longest_streak():
    settlements = [
        _settlement(ts=0, won=True, gross=1.0, net=0.9),
        _settlement(ts=1, won=False, gross=-1.0, net=-1.2),
        _settlement(ts=2, won=False, gross=-1.0, net=-1.2),
        _settlement(ts=3, won=False, gross=-1.0, net=-1.2),
        _settlement(ts=4, won=True, gross=1.0, net=0.9),
        _settlement(ts=5, won=False, gross=-1.0, net=-1.2),
    ]
    assert max_consecutive_losses(settlements) == 3


def test_max_consecutive_losses_zero_with_no_losses():
    settlements = [_settlement(ts=i, won=True, gross=1.0, net=0.9) for i in range(5)]
    assert max_consecutive_losses(settlements) == 0


def test_max_consecutive_losses_uses_entry_order_not_list_order():
    # Deliberately out-of-order input; the function must sort by entry_ts.
    # In list order this looks like a loss, then a win breaking the streak,
    # then two more losses — a naive scan over list order would see two
    # separate streaks of 1 and 2. Sorted by entry_ts (0,1,2,3), the win is
    # actually FIRST, so it's really one continuous streak of 3.
    settlements = [
        _settlement(ts=3, won=False, gross=-1.0, net=-1.2),
        _settlement(ts=0, won=True, gross=1.0, net=0.9),
        _settlement(ts=1, won=False, gross=-1.0, net=-1.2),
        _settlement(ts=2, won=False, gross=-1.0, net=-1.2),
    ]
    assert max_consecutive_losses(settlements) == 3  # ts=1,2,3 sorted is the real streak


def test_max_consecutive_losses_empty_settlements():
    assert max_consecutive_losses([]) == 0


# --- r_multiples ----------------------------------------------------------------


def test_r_multiples_full_loss_is_minus_one_r():
    settlements = [
        _settlement(ts=0, won=False, entry_price_cents=50, quantity=10, gross=-5.0, net=-5.2)
    ]
    (r,) = r_multiples(settlements)
    assert r == pytest.approx(-5.2 / 5.0)


def test_r_multiples_win_is_positive():
    settlements = [
        _settlement(ts=0, won=True, entry_price_cents=50, quantity=10, gross=5.0, net=4.8)
    ]
    (r,) = r_multiples(settlements)
    assert r > 0


def test_r_multiples_empty_for_no_trades():
    assert r_multiples([]) == ()


# --- compute_segment_metrics wiring --------------------------------------------


def test_compute_segment_metrics_includes_new_fields():
    # 8 wins of +1.2, 4 losses of -1.0 -> total net profit positive.
    settlements = [
        _settlement(
            ts=i,
            won=i % 3 != 0,
            gross=1.5 if i % 3 != 0 else -1.0,
            net=1.2 if i % 3 != 0 else -1.0,
        )
        for i in range(12)
    ]
    equity_curve = [(i, 100.0 + i) for i in range(12)]
    metrics = compute_segment_metrics("test", settlements, equity_curve)
    assert metrics.max_consecutive_losses >= 0
    assert isinstance(metrics.r_multiples, tuple)
    assert len(metrics.r_multiples) == 12
    # 12 trades >= 10, so concentration should be computed (not None) as
    # long as total profit is positive.
    assert metrics.top10_concentration_pct is not None


# --- flat_sizing_net_pnl_usd ---------------------------------------------------


def test_flat_sizing_recomputes_pnl_at_fixed_quantity():
    # Original settlement used quantity=10; flat sizing at 1 contract should
    # scale gross linearly but fee is recomputed at the new quantity.
    settlements = [
        _settlement(ts=0, won=True, entry_price_cents=40, quantity=10, gross=6.0, net=5.8)
    ]
    flat_pnl = flat_sizing_net_pnl_usd(settlements, flat_quantity=1)
    expected_gross = (1.0 - 0.40) * 1
    expected_fee = entry_fee_dollars(40, 1)
    assert flat_pnl == pytest.approx(expected_gross - expected_fee)


def test_flat_sizing_loss_is_negative():
    settlements = [
        _settlement(ts=0, won=False, entry_price_cents=40, quantity=10, gross=-4.0, net=-4.2)
    ]
    flat_pnl = flat_sizing_net_pnl_usd(settlements, flat_quantity=1)
    assert flat_pnl < 0


def test_flat_sizing_can_expose_a_kelly_compounding_artifact():
    """A strategy that looks profitable ONLY because later (larger, Kelly-
    compounded) positions happened to win should look much worse — or even
    unprofitable — under flat sizing, since flat sizing removes the
    size-timing effect entirely (tasks.md 8.2's whole point)."""
    settlements = [
        _settlement(ts=0, won=False, entry_price_cents=50, quantity=1, gross=-0.5, net=-0.55),
        _settlement(ts=1, won=False, entry_price_cents=50, quantity=1, gross=-0.5, net=-0.55),
        # A late, large win drives the ORIGINAL (variable-sized) net positive.
        _settlement(ts=2, won=True, entry_price_cents=50, quantity=100, gross=50.0, net=48.0),
    ]
    original_net = sum(s.net_pnl_usd for s in settlements)
    flat_net = flat_sizing_net_pnl_usd(settlements, flat_quantity=1)
    assert original_net > 0
    # At flat sizing (1 contract every time), the same win/loss PATTERN
    # yields a much smaller, still-positive-but-far-less-impressive total.
    assert flat_net < original_net


def test_summary_includes_new_metrics_text():
    settlements = [_settlement(ts=i, won=True, gross=1.0, net=0.9) for i in range(12)]
    equity_curve = [(i, 100.0 + i) for i in range(12)]
    metrics = compute_segment_metrics("test", settlements, equity_curve)
    summary = metrics.summary()
    assert "top10_concentration" in summary
    assert "max_consec_losses" in summary
    assert "flat_sizing_net_pnl" in summary
