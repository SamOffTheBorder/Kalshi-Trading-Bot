"""In-memory arm/halt state for the dashboard's Start and kill-switch controls.

Trading starts stopped, always (tasks.md 9.2) — opening the dashboard is never
the same act as risking money. There is no live-trading process to actually
arm yet (that's tasks.md §4-§7); this tracks the *operator's* intent so the
control wiring, and the "trading is stopped" banner, are real now and simply
gain a live process to drive once one exists. Process-local and in-memory on
purpose: a restart of the dashboard always comes back stopped.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ControlState:
    armed: bool = False
    halted: bool = False
    last_changed_at: datetime | None = None
    last_reason: str | None = None


class ControlPanel:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = ControlState()

    def snapshot(self) -> ControlState:
        with self._lock:
            return ControlState(**vars(self._state))

    def arm(self) -> ControlState:
        with self._lock:
            self._state.armed = True
            self._state.halted = False
            self._state.last_changed_at = datetime.now(UTC)
            self._state.last_reason = "operator start"
            return ControlState(**vars(self._state))

    def kill(self, reason: str = "operator kill switch") -> ControlState:
        with self._lock:
            self._state.armed = False
            self._state.halted = True
            self._state.last_changed_at = datetime.now(UTC)
            self._state.last_reason = reason
            return ControlState(**vars(self._state))


_panel = ControlPanel()


def get_control_panel() -> ControlPanel:
    return _panel
