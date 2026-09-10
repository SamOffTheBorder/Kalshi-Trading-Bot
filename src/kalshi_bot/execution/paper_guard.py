"""Fail-closed invariants for every paper/shadow entry point.

This guard is intentionally small and dependency-free.  Domain adapters call it
before constructing authenticated clients or evaluating an entry; it never
creates a broker and therefore cannot accidentally provide a live-order path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kalshi_bot.config.settings import Settings

PaperMode = Literal["paper", "shadow"]


class PaperExecutionError(RuntimeError):
    """Raised when a paper/shadow safety invariant is not satisfied."""


@dataclass(frozen=True)
class PaperExecutionGuard:
    """Validated, non-secret paper-run configuration.

    ``require_authenticated`` is true for callers that need signed Kalshi
    reads (BRTI or margin).  Public-only simulations can opt out while still
    requiring ``PAPER_TRADING`` and a paper/shadow mode.
    """

    mode: PaperMode
    require_authenticated: bool
    ledger_path: Path
    config_fingerprint: str

    @classmethod
    def validate(
        cls,
        settings: Settings,
        *,
        mode: PaperMode,
        require_authenticated: bool = True,
        ledger_path: Path | None = None,
    ) -> PaperExecutionGuard:
        if mode not in {"paper", "shadow"}:
            raise PaperExecutionError(f"unsupported paper mode: {mode!r}")
        if not settings.paper_trading:
            raise PaperExecutionError("PAPER_TRADING must be true for paper/shadow runs")
        if require_authenticated and not settings.kalshi_use_demo_env:
            raise PaperExecutionError(
                "KALSHI_USE_DEMO_ENV must be true for authenticated paper/shadow reads"
            )

        path = Path(ledger_path or settings.db_path)
        valid_suffix = path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        if path.name in {"", ".", ".."} or not valid_suffix:
            raise PaperExecutionError(
                f"paper ledger must be a local SQLite file (.db/.sqlite/.sqlite3): {path}"
            )
        if path.is_dir():
            raise PaperExecutionError(f"paper ledger path is a directory: {path}")

        # Keep the fingerprint useful for audit logs without including secrets.
        fingerprint = (
            f"mode={mode};auth={int(require_authenticated)};db={path.resolve()}"
        )
        return cls(
            mode=mode,
            require_authenticated=require_authenticated,
            ledger_path=path,
            config_fingerprint=fingerprint,
        )

    @staticmethod
    def assert_paper_adapter(adapter: object) -> None:
        """Reject an adapter that exposes a mutating/live broker surface.

        Paper adapters may implement ``place_order`` for simulation, but a
        live Kalshi client exposes ``create_order``.  This explicit boundary is
        checked before dependency injection in the orchestrator.
        """

        if hasattr(adapter, "create_order") or hasattr(adapter, "amend_order"):
            raise PaperExecutionError(
                "mutating exchange adapter cannot be injected into a paper run"
            )
        broker_name = getattr(adapter, "broker_name", None)
        if broker_name not in {None, "paper", "shadow"}:
            raise PaperExecutionError(f"unsupported non-paper adapter: {broker_name!r}")


__all__ = ["PaperExecutionError", "PaperExecutionGuard", "PaperMode"]
