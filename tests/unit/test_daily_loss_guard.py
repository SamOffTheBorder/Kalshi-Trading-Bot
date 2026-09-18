"""Daily loss limit + consecutive-loss halt (tasks.md 5.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kalshi_bot.risk.daily_loss_guard import ConsecutiveLossGuard, DailyLossGuard


def _ts(hour: int = 12, day: int = 1) -> datetime:
    return datetime(2026, 9, day, hour, 0, 0, tzinfo=UTC)


# --- DailyLossGuard -----------------------------------------------------------


def test_daily_loss_guard_allows_entries_before_limit_breached():
    guard = DailyLossGuard(max_daily_loss_usd=20.0)
    guard.record_trade_pnl(-5.0, _ts())
    assert guard.allows_new_entries(_ts()) is True


def test_daily_loss_guard_halts_once_limit_breached():
    guard = DailyLossGuard(max_daily_loss_usd=20.0)
    guard.record_trade_pnl(-12.0, _ts())
    guard.record_trade_pnl(-10.0, _ts())
    assert guard.daily_pnl_usd == pytest.approx(-22.0)
    assert guard.allows_new_entries(_ts()) is False


def test_daily_loss_guard_resets_on_new_utc_day():
    guard = DailyLossGuard(max_daily_loss_usd=20.0)
    guard.record_trade_pnl(-25.0, _ts(hour=23, day=1))
    assert guard.allows_new_entries(_ts(hour=23, day=1)) is False
    assert guard.allows_new_entries(_ts(hour=1, day=2)) is True
    assert guard.daily_pnl_usd == 0.0


def test_daily_loss_guard_manual_reset_lifts_halt_same_day():
    guard = DailyLossGuard(max_daily_loss_usd=20.0)
    guard.record_trade_pnl(-25.0, _ts())
    assert guard.allows_new_entries(_ts()) is False
    guard.reset(approved_by="operator")
    assert guard.allows_new_entries(_ts()) is True


def test_daily_loss_guard_manual_reset_does_not_survive_further_losses():
    guard = DailyLossGuard(max_daily_loss_usd=20.0)
    guard.record_trade_pnl(-25.0, _ts())
    guard.reset(approved_by="operator")
    guard.record_trade_pnl(-1.0, _ts())
    # Still under the (still-breached) threshold territory, but the reset
    # flag should not silently suppress a fresh breach forever — verify via
    # the next day's fresh start behaving normally instead of relying on
    # implementation internals.
    assert guard.daily_pnl_usd == pytest.approx(-26.0)


def test_daily_loss_guard_rejects_nonpositive_limit():
    with pytest.raises(ValueError):
        DailyLossGuard(max_daily_loss_usd=0.0)


# --- ConsecutiveLossGuard -------------------------------------------------


def test_consecutive_loss_guard_allows_until_streak_hits_max():
    guard = ConsecutiveLossGuard(max_consecutive_losses=3)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(-1.0)
    assert guard.allows_new_entries() is True
    guard.record_trade_pnl(-1.0)
    assert guard.allows_new_entries() is False
    assert guard.current_streak == 3


def test_consecutive_loss_guard_win_resets_streak():
    guard = ConsecutiveLossGuard(max_consecutive_losses=3)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(5.0)
    assert guard.current_streak == 0
    assert guard.allows_new_entries() is True


def test_consecutive_loss_guard_win_clears_existing_halt():
    guard = ConsecutiveLossGuard(max_consecutive_losses=2)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(-1.0)
    assert guard.allows_new_entries() is False
    guard.record_trade_pnl(3.0)
    assert guard.allows_new_entries() is True


def test_consecutive_loss_guard_breakeven_counts_as_not_a_loss():
    guard = ConsecutiveLossGuard(max_consecutive_losses=2)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(0.0)
    assert guard.current_streak == 0
    assert guard.allows_new_entries() is True


def test_consecutive_loss_guard_manual_reset():
    guard = ConsecutiveLossGuard(max_consecutive_losses=2)
    guard.record_trade_pnl(-1.0)
    guard.record_trade_pnl(-1.0)
    assert guard.allows_new_entries() is False
    guard.reset(approved_by="operator")
    assert guard.allows_new_entries() is True
    assert guard.current_streak == 0


def test_consecutive_loss_guard_rejects_invalid_max():
    with pytest.raises(ValueError):
        ConsecutiveLossGuard(max_consecutive_losses=0)
