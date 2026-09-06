"""Daily loss limit and consecutive-loss halt (tasks.md 5.4).

Two trade-outcome-driven guards, distinct from `DrawdownGuard`'s
equity-curve-driven PAUSE/HALT:

- **Daily loss limit**: total realized PnL within the current calendar day
  (UTC) must not fall below `-max_daily_loss_usd`. Resets at UTC midnight —
  a bad day doesn't bleed into the next one's budget, but also can't be
  gamed by trading through midnight to reset a limit mid-session.
- **Consecutive-loss halt**: `max_consecutive_losses` losing trades in a row
  (any winning trade resets the streak) halts new entries. This is a
  distinct failure mode from a slow bleed: N sharp losses in a row usually
  means the strategy's edge assumption broke for current conditions, not
  that a variance-typical drawdown is in progress.

Both are sticky within their triggering condition: `allows_new_entries()`
returns False until the day rolls over (daily loss) or a winning trade
resets the streak (consecutive losses) — there is deliberately no "wait it
out" recovery within the same day/streak, unlike `DrawdownGuard`'s PAUSE
state which can recover without a human. A human can still override via
`reset()`, same shape as `DrawdownGuard.reset()`.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from loguru import logger


class DailyLossGuard:
    """Halts new entries once today's (UTC) realized PnL breaches
    `-max_daily_loss_usd`."""

    def __init__(self, *, max_daily_loss_usd: float) -> None:
        if max_daily_loss_usd <= 0:
            raise ValueError("max_daily_loss_usd must be positive")
        self.max_daily_loss_usd = max_daily_loss_usd
        self._current_date = None
        self._daily_pnl_usd = 0.0
        self._halted_today = False
        self._manually_reset = False

    @property
    def daily_pnl_usd(self) -> float:
        return self._daily_pnl_usd

    def _roll_day_if_needed(self, ts: datetime) -> None:
        trade_date = ts.astimezone(UTC).date()
        if self._current_date is None:
            self._current_date = trade_date
        elif trade_date != self._current_date:
            logger.info(
                "DailyLossGuard: new UTC day ({} -> {}), resetting daily PnL and halt",
                self._current_date,
                trade_date,
            )
            self._current_date = trade_date
            self._daily_pnl_usd = 0.0
            self._halted_today = False
            self._manually_reset = False

    def record_trade_pnl(self, pnl_usd: float, ts: datetime) -> None:
        """Record one closed trade's realized PnL. Call only on a settled
        exit, not on unrealized/mark-to-market PnL."""
        self._roll_day_if_needed(ts)
        self._daily_pnl_usd += pnl_usd
        if self._daily_pnl_usd <= -self.max_daily_loss_usd and not self._manually_reset:
            if not self._halted_today:
                logger.warning(
                    "DailyLossGuard HALT: daily PnL {:.2f} breached -{:.2f}",
                    self._daily_pnl_usd,
                    self.max_daily_loss_usd,
                )
            self._halted_today = True

    def allows_new_entries(self, ts: datetime) -> bool:
        self._roll_day_if_needed(ts)
        return not self._halted_today

    def reset(self, *, approved_by: str) -> None:
        """Explicit human override — lifts today's halt without waiting for
        the UTC day to roll over."""
        logger.warning("DailyLossGuard reset by {}", approved_by)
        self._halted_today = False
        self._manually_reset = True


class ConsecutiveLossGuard:
    """Halts new entries after `max_consecutive_losses` losing trades in a
    row. Any winning (or breakeven) trade resets the streak."""

    def __init__(self, *, max_consecutive_losses: int) -> None:
        if max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        self.max_consecutive_losses = max_consecutive_losses
        self._streak = 0
        self._halted = False
        self._recent_outcomes: deque[bool] = deque(maxlen=max_consecutive_losses)

    @property
    def current_streak(self) -> int:
        return self._streak

    def record_trade_pnl(self, pnl_usd: float) -> None:
        is_loss = pnl_usd < 0
        self._recent_outcomes.append(is_loss)
        if is_loss:
            self._streak += 1
        else:
            self._streak = 0
            self._halted = False  # a win always clears a prior halt too
        if self._streak >= self.max_consecutive_losses:
            if not self._halted:
                logger.warning(
                    "ConsecutiveLossGuard HALT: {} consecutive losses >= {}",
                    self._streak,
                    self.max_consecutive_losses,
                )
            self._halted = True

    def allows_new_entries(self) -> bool:
        return not self._halted

    def reset(self, *, approved_by: str) -> None:
        logger.warning("ConsecutiveLossGuard reset by {}", approved_by)
        self._streak = 0
        self._halted = False
        self._recent_outcomes.clear()


__all__ = ["ConsecutiveLossGuard", "DailyLossGuard"]
