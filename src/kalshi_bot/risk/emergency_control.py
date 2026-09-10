"""Composite emergency control: DrawdownGuard + DailyLossGuard +
ConsecutiveLossGuard behind one `allows_new_entries()` gate, optionally
wired to the dashboard's `ControlPanel` (paper-trading-and-notify tasks.md
§3.1).

Three independent failure modes, three independent guards — each already
has its own module and its own reasoning for existing:

- `DrawdownGuard` — equity-curve PAUSE/HALT from a (trailing or all-time)
  peak.
- `DailyLossGuard` — a hard floor on realized PnL within the current UTC
  day, distinct from a slow equity bleed.
- `ConsecutiveLossGuard` — N losses in a row, which usually means the
  strategy's edge assumption broke for current conditions rather than
  ordinary variance.

`EmergencyControl` composes them: new entries are allowed only when ALL
THREE agree. Any one guard tripping also trips the dashboard's
`ControlPanel.kill()` (when a panel is attached) — an operator watching the
dashboard sees the SAME halt state a live loop is enforcing, not a separate
number that could silently disagree. `resume()` is the one explicit human
action that clears every guard and re-arms the panel together — no
individual guard auto-recovers into a resumed panel state on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from kalshi_bot.risk.daily_loss_guard import ConsecutiveLossGuard, DailyLossGuard
from kalshi_bot.risk.drawdown_guard import DrawdownGuard, GuardState
from kalshi_bot.web.control_state import ControlPanel


@dataclass(frozen=True)
class HaltState:
    halted: bool
    reason: str | None


class EmergencyControl:
    def __init__(
        self,
        *,
        drawdown_guard: DrawdownGuard,
        daily_loss_guard: DailyLossGuard,
        consecutive_loss_guard: ConsecutiveLossGuard,
        control_panel: ControlPanel | None = None,
    ) -> None:
        self.drawdown_guard = drawdown_guard
        self.daily_loss_guard = daily_loss_guard
        self.consecutive_loss_guard = consecutive_loss_guard
        self._control_panel = control_panel
        self._tripped_reason: str | None = None

    # -- feed loop events in ------------------------------------------------

    def update_equity(self, equity_usd: float, ts: int | None = None) -> None:
        """Feed the latest mark-to-market equity to the drawdown guard."""
        self.drawdown_guard.update(equity_usd, ts)
        if self.drawdown_guard.state == GuardState.HALTED:
            self._trip(f"drawdown guard: {self.drawdown_guard.drawdown_all_time:.1%} from peak")

    def record_trade_pnl(self, pnl_usd: float, ts: datetime) -> None:
        """Feed one settled trade's realized PnL to the daily-loss and
        consecutive-loss guards."""
        self.daily_loss_guard.record_trade_pnl(pnl_usd, ts)
        self.consecutive_loss_guard.record_trade_pnl(pnl_usd)
        if not self.daily_loss_guard.allows_new_entries(ts):
            self._trip(f"daily loss guard: {self.daily_loss_guard.daily_pnl_usd:.2f} realized")
        if not self.consecutive_loss_guard.allows_new_entries():
            self._trip(
                f"consecutive loss guard: {self.consecutive_loss_guard.current_streak} "
                "losses in a row"
            )

    def _trip(self, reason: str) -> None:
        already_halted = self._control_panel is not None and self._control_panel.snapshot().halted
        self._tripped_reason = reason
        if self._control_panel is not None and not already_halted:
            logger.warning("EmergencyControl trip: {}", reason)
            self._control_panel.kill(reason=reason)
        elif self._control_panel is None:
            logger.warning("EmergencyControl trip (no panel attached): {}", reason)

    # -- gate ----------------------------------------------------------------

    def allows_new_entries(self, ts: datetime) -> bool:
        if self._control_panel is not None and self._control_panel.snapshot().halted:
            return False
        return (
            self.drawdown_guard.allows_new_entries()
            and self.daily_loss_guard.allows_new_entries(ts)
            and self.consecutive_loss_guard.allows_new_entries()
        )

    def snapshot(self) -> HaltState:
        panel_halted = self._control_panel.snapshot().halted if self._control_panel else False
        halted = panel_halted or not (
            self.drawdown_guard.allows_new_entries()
            and self.daily_loss_guard.allows_new_entries
            and self.consecutive_loss_guard.allows_new_entries()
        )
        return HaltState(halted=bool(halted), reason=self._tripped_reason)

    # -- explicit human recovery ----------------------------------------------

    def resume(self, *, approved_by: str) -> None:
        """Clear every guard and re-arm the panel together. The one
        deliberate exception is `DrawdownGuard.HALT`, which stays sticky per
        its own module contract unless the guard was built with
        `allow_reentry_after_halt=True` — resetting it here would silently
        override that documented safety property. Reset it directly via
        `drawdown_guard.reset()` (or rebuild it) if that's truly intended."""
        logger.warning("EmergencyControl resume approved by {}", approved_by)
        self.daily_loss_guard.reset(approved_by=approved_by)
        self.consecutive_loss_guard.reset(approved_by=approved_by)
        self._tripped_reason = None
        if self._control_panel is not None:
            self._control_panel.arm()
