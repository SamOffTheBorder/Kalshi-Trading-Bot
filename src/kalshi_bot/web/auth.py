"""Session authentication for the locally operated dashboard.

The dashboard has no user accounts.  A process-local session is deliberately
enough: restarting the dashboard invalidates access and requires either the
launcher bootstrap or the configured LAN secret again.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

SESSION_TTL_S = 12 * 60 * 60
BOOTSTRAP_TTL_S = 5 * 60


@dataclass(frozen=True)
class DashboardSession:
    token: str
    csrf_token: str
    expires_at: float


class DashboardAuth:
    """In-memory, single-operator authentication state."""

    def __init__(self, *, bootstrap_token: str | None, login_secret: str | None) -> None:
        self._bootstrap_token = bootstrap_token
        self._bootstrap_expires_at = time.monotonic() + BOOTSTRAP_TTL_S
        self._login_secret = login_secret
        self._sessions: dict[str, DashboardSession] = {}
        self._lock = threading.Lock()

    def exchange_bootstrap(self, token: str) -> DashboardSession | None:
        with self._lock:
            if (
                self._bootstrap_token is None
                or time.monotonic() > self._bootstrap_expires_at
                or not secrets.compare_digest(token, self._bootstrap_token)
            ):
                return None
            self._bootstrap_token = None
            return self._issue_session_locked()

    def login(self, secret: str) -> DashboardSession | None:
        with self._lock:
            if self._login_secret is None or not secrets.compare_digest(secret, self._login_secret):
                return None
            return self._issue_session_locked()

    def session(self, token: str | None) -> DashboardSession | None:
        if not token:
            return None
        with self._lock:
            current = self._sessions.get(token)
            if current is None:
                return None
            if time.monotonic() >= current.expires_at:
                self._sessions.pop(token, None)
                return None
            return current

    def _issue_session_locked(self) -> DashboardSession:
        session = DashboardSession(
            token=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            expires_at=time.monotonic() + SESSION_TTL_S,
        )
        self._sessions[session.token] = session
        return session
