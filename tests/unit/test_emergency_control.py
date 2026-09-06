"""EmergencyControl: composes DrawdownGuard + DailyLossGuard +
ConsecutiveLossGuard, wired to the dashboard's ControlPanel (tasks.md 5.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from kalshi_bot.risk.daily_loss_guard import ConsecutiveLossGuard, DailyLossGuard
from kalshi_bot.risk.drawdown_guard import DrawdownGuard
from kalshi_bot.risk.emergency_control import EmergencyControl
from kalshi_bot.web.control_state import ControlPanel


def _ts(hour: int = 12) -> datetime:
    return datetime(2026, 9, 6, hour, 0, 0, tzinfo=UTC)


def _make_control(control_panel: ControlPanel | None = None) -> EmergencyControl:
    return EmergencyControl(
        drawdown_guard=DrawdownGuard(pause_pct=0.10, halt_pct=0.25, initial_equity=1000.0),
        daily_loss_guard=DailyLossGuard(max_daily_loss_usd=20.0),
        consecutive_loss_guard=ConsecutiveLossGuard(max_consecutive_losses=3),
        control_panel=control_panel,
    )


def test_allows_new_entries_when_all_guards_normal():
    control = _make_control()
    assert control.allows_new_entries(_ts()) is True


def test_drawdown_halt_blocks_new_entries():
    control = _make_control()
    control.update_equity(1000.0)
    control.update_equity(700.0)  # 30% drawdown, past 25% halt
    assert control.allows_new_entries(_ts()) is False


def test_daily_loss_breach_blocks_new_entries():
    control = _make_control()
    control.record_trade_pnl(-25.0, _ts())
    assert control.allows_new_entries(_ts()) is False


def test_consecutive_losses_block_new_entries():
    control = _make_control()
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    assert control.allows_new_entries(_ts()) is False


def test_drawdown_halt_trips_control_panel_kill():
    panel = ControlPanel()
    panel.arm()
    control = _make_control(control_panel=panel)
    control.update_equity(1000.0)
    control.update_equity(700.0)
    assert panel.snapshot().halted is True
    assert panel.snapshot().armed is False


def test_daily_loss_trips_control_panel_kill():
    panel = ControlPanel()
    panel.arm()
    control = _make_control(control_panel=panel)
    control.record_trade_pnl(-25.0, _ts())
    assert panel.snapshot().halted is True


def test_consecutive_loss_trips_control_panel_kill():
    panel = ControlPanel()
    panel.arm()
    control = _make_control(control_panel=panel)
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    assert panel.snapshot().halted is True


def test_control_panel_kill_is_not_retriggered_on_every_subsequent_loss():
    """Trip fires once per transition, not on every call after the guard is
    already halted — verified indirectly via the panel's last_reason not
    needing repeated kill() calls to stay halted."""
    panel = ControlPanel()
    panel.arm()
    control = _make_control(control_panel=panel)
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    control.record_trade_pnl(-1.0, _ts())
    first_reason = panel.snapshot().last_reason
    control.record_trade_pnl(-1.0, _ts())
    assert panel.snapshot().last_reason == first_reason


def test_resume_clears_all_guards_and_rearms_panel():
    panel = ControlPanel()
    panel.arm()
    control = _make_control(control_panel=panel)
    control.record_trade_pnl(-25.0, _ts())
    assert control.allows_new_entries(_ts()) is False
    assert panel.snapshot().halted is True

    control.resume(approved_by="operator")

    assert control.allows_new_entries(_ts()) is True
    assert panel.snapshot().armed is True
    assert panel.snapshot().halted is False


def test_works_without_a_control_panel():
    """control_panel is optional — EmergencyControl must be fully usable
    with no dashboard attached (e.g. backtests, unit tests elsewhere)."""
    control = _make_control(control_panel=None)
    control.record_trade_pnl(-25.0, _ts())
    assert control.allows_new_entries(_ts()) is False
    control.resume(approved_by="operator")
    assert control.allows_new_entries(_ts()) is True
