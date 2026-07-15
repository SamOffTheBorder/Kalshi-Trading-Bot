"""Per-broker drawdown state machine.

NORMAL -> PAUSED (no new entries) at the pause threshold; -> HALTED at the
halt threshold. PAUSED recovers to NORMAL when drawdown shrinks back below
the pause line. HALTED is sticky: only an explicit human-initiated reset
clears it (wired to EmergencyControl.resume in a later change).

Thresholds arrive via constructor from Settings — the single definition.
v1 shipped three contradictory copies of these numbers; this class is the
only place the comparison logic exists.
"""

from __future__ import annotations

from enum import StrEnum

from loguru import logger


class GuardState(StrEnum):
    NORMAL = "NORMAL"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class DrawdownGuard:
    def __init__(self, *, pause_pct: float, halt_pct: float, initial_equity: float) -> None:
        if not 0 < pause_pct < halt_pct < 1:
            raise ValueError(f"require 0 < pause_pct ({pause_pct}) < halt_pct ({halt_pct}) < 1")
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        self.pause_pct = pause_pct
        self.halt_pct = halt_pct
        self.peak_equity = initial_equity
        self.state = GuardState.NORMAL
        self._drawdown = 0.0

    @property
    def drawdown(self) -> float:
        """Most recent drawdown-from-peak, for dashboards/status."""
        return self._drawdown

    def update(self, current_equity: float) -> GuardState:
        """Feed the latest equity; returns the (possibly new) state."""
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
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
