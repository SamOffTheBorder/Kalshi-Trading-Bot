"""Per-broker drawdown state machine.

NORMAL -> PAUSED (no new entries) at the pause threshold; -> HALTED at the
halt threshold. PAUSED recovers to NORMAL when drawdown shrinks back below
the pause line. HALTED is sticky: only an explicit human-initiated reset
clears it (wired to EmergencyControl.resume in a later change).

Drawdown is measured against a TRAILING-WINDOW peak, not the all-time peak.
Backtest runs #3-#5 exposed why: in a settle-to-flat system, a paused book
has constant equity, so drawdown from an all-time peak can never shrink —
PAUSED became permanently sticky and starved every out-of-sample segment.
With a trailing peak, an old peak ages out of the window and the guard
re-arms after at most `peak_window_s` of no new losses. HALTED remains
all-time-sticky regardless.

Thresholds arrive via constructor from Settings — the single definition.
v1 shipped three contradictory copies of these numbers; this class is the
only place the comparison logic exists.
"""

from __future__ import annotations

from collections import deque
from enum import StrEnum

from loguru import logger


class GuardState(StrEnum):
    NORMAL = "NORMAL"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class DrawdownGuard:
    def __init__(
        self,
        *,
        pause_pct: float,
        halt_pct: float,
        initial_equity: float,
        peak_window_s: int | None = None,
    ) -> None:
        """`peak_window_s=None` keeps the classic all-time-peak behavior
        (callers that don't pass timestamps). With a window, `update()` must
        be given `ts` so peaks can age out."""
        if not 0 < pause_pct < halt_pct < 1:
            raise ValueError(f"require 0 < pause_pct ({pause_pct}) < halt_pct ({halt_pct}) < 1")
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if peak_window_s is not None and peak_window_s <= 0:
            raise ValueError("peak_window_s must be positive (or None for all-time peak)")
        self.pause_pct = pause_pct
        self.halt_pct = halt_pct
        self.peak_window_s = peak_window_s
        self.peak_equity = initial_equity
        self.state = GuardState.NORMAL
        self._drawdown = 0.0
        # monotonic-decreasing deque of (ts, equity); front is the window max
        self._peaks: deque[tuple[int, float]] = deque()

    @property
    def drawdown(self) -> float:
        """Most recent drawdown-from-peak, for dashboards/status."""
        return self._drawdown

    def _window_peak(self, current_equity: float, ts: int) -> float:
        while self._peaks and self._peaks[-1][1] <= current_equity:
            self._peaks.pop()
        self._peaks.append((ts, current_equity))
        assert self.peak_window_s is not None
        while self._peaks and self._peaks[0][0] <= ts - self.peak_window_s:
            self._peaks.popleft()
        return self._peaks[0][1]

    def update(self, current_equity: float, ts: int | None = None) -> GuardState:
        """Feed the latest equity; returns the (possibly new) state."""
        if self.peak_window_s is None:
            self.peak_equity = max(self.peak_equity, current_equity)
        elif ts is None:
            raise ValueError("guard has a trailing peak window; update() requires ts")
        else:
            self.peak_equity = self._window_peak(current_equity, ts)
        dd = 1.0 - (current_equity / self.peak_equity)
        self._drawdown = dd

        if self.state == GuardState.HALTED:
            return self.state  # sticky until explicit reset

        if dd >= self.halt_pct:
            logger.warning("DrawdownGuard HALT: drawdown {:.1%} >= {:.1%}", dd, self.halt_pct)
            self.state = GuardState.HALTED
        elif dd >= self.pause_pct:
            if self.state != GuardState.PAUSED:
                logger.warning("DrawdownGuard PAUSE: drawdown {:.1%} >= {:.1%}", dd, self.pause_pct)
            self.state = GuardState.PAUSED
        else:
            self.state = GuardState.NORMAL
        return self.state

    def allows_new_entries(self) -> bool:
        return self.state == GuardState.NORMAL

    def reset(self, *, approved_by: str) -> None:
        """Explicit human-initiated recovery from HALTED (or any state)."""
        logger.warning("DrawdownGuard reset by {}", approved_by)
        self.state = GuardState.NORMAL
