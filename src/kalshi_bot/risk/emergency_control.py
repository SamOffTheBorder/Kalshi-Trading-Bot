"""EmergencyControl: the single point that decides whether new entries are
allowed, composing every automatic circuit breaker (tasks.md 5.4).

Referenced but deliberately not built until now: `DrawdownGuard`'s own
docstring says HALTED is "wired to EmergencyControl.resume in a later
change," and the dashboard's kill switch (tasks.md 9.4) says its
`ControlPanel.kill()` is "not yet wired to EmergencyControl because that
class doesn't exist until §5 (risk layer) is built." This is that class.

Composes three independent guards, each catching a different failure mode
found in Phase 1's backtests:

- `DrawdownGuard` — equity-curve drawdown (PAUSE at a trailing-window
  reference, HALT at the all-time peak).
- `DailyLossGuard` — a bad calendar day's realized PnL, independent of the
  broader equity curve.
- `ConsecutiveLossGuard` — a losing streak, which usually means the
  strategy's edge assumption broke for current conditions rather than
  ordinary variance.

`allows_new_entries()` is a simple AND across all three — any one guard
objecting blocks new entries. `record_trade_pnl()` feeds every PnL-driven
guard from one call so callers don't have to remember to update three
objects individually and can't update some but not others.

Wired to the dashboard's `ControlPanel` (tasks.md 9.2/9.4): any automatic
trip calls `ControlPanel.kill()` so the "trading is stopped" banner and the
kill-switch state are the SAME truth the risk layer is enforcing, not a
second copy of it. `ControlPanel` is passed in rather than imported at
module scope — `risk/` has no business depending on `web/` by default, and
tests can exercise `EmergencyControl` with no dashboard at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from loguru import logger

from kalshi_bot.risk.daily_loss_guard import ConsecutiveLossGuard, DailyLossGuard
from kalshi_bot.risk.drawdown_guard import DrawdownGuard


class SupportsKillAndArm(Protocol):
    """The subset of `web.control_state.ControlPanel` this class needs —
    structural typing so `risk/` doesn't import `web/`."""

    def kill(self, reason: str = ...) -> object: ...
    def arm(self) -> object: ...


class EmergencyControl:
    def __init__(
        self,
        *,
        drawdown_guard: DrawdownGuard,
        daily_loss_guard: DailyLossGuard,
        consecutive_loss_guard: ConsecutiveLossGuard,
        control_panel: SupportsKillAndArm | None = None,
    ) -> None:
        self.drawdown_guard = drawdown_guard
        self.daily_loss_guard = daily_loss_guard
        self.consecutive_loss_guard = consecutive_loss_guard
        self._control_panel = control_panel

    def allows_new_entries(self, ts: datetime) -> bool:
        return (
            self.drawdown_guard.allows_new_entries()
            and self.daily_loss_guard.allows_new_entries(ts)
            and self.consecutive_loss_guard.allows_new_entries()
        )

    def update_equity(self, current_equity: float, ts: int | None = None) -> None:
        """Feed the latest equity mark to the drawdown guard. Trips the
        dashboard kill switch the moment HALT is reached (PAUSE alone does
        not kill — it's meant to self-recover without operator action)."""
        previous_state = self.drawdown_guard.state
        new_state = self.drawdown_guard.update(current_equity, ts)
        if new_state != previous_state and str(new_state) == "HALTED":
            self._trip("drawdown guard HALTED")

    def record_trade_pnl(self, pnl_usd: float, ts: datetime) -> None:
        """Feed one closed trade's realized PnL to both PnL-driven guards.
        Trips the kill switch the instant either one halts."""
        daily_was_allowed = self.daily_loss_guard.allows_new_entries(ts)
        streak_was_allowed = self.consecutive_loss_guard.allows_new_entries()

        self.daily_loss_guard.record_trade_pnl(pnl_usd, ts)
        self.consecutive_loss_guard.record_trade_pnl(pnl_usd)

        if daily_was_allowed and not self.daily_loss_guard.allows_new_entries(ts):
            self._trip("daily loss limit breached")
        if streak_was_allowed and not self.consecutive_loss_guard.allows_new_entries():
            self._trip("consecutive-loss halt")

    def _trip(self, reason: str) -> None:
        logger.critical("EmergencyControl: TRIPPED ({})", reason)
        if self._control_panel is not None:
            self._control_panel.kill(reason=f"EmergencyControl: {reason}")

    def resume(self, *, approved_by: str) -> None:
        """Explicit human-initiated recovery across every guard at once,
        plus re-arming the dashboard control panel — the single action that
        undoes everything `_trip` did. Never automatic."""
        logger.warning("EmergencyControl: resume approved by {}", approved_by)
        self.drawdown_guard.reset(approved_by=approved_by)
        self.daily_loss_guard.reset(approved_by=approved_by)
        self.consecutive_loss_guard.reset(approved_by=approved_by)
        if self._control_panel is not None:
            self._control_panel.arm()


__all__ = ["EmergencyControl", "SupportsKillAndArm"]
