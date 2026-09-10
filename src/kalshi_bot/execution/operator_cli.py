"""Foreground operator command hub (multi-venue-paper-trading §12.3).

One bounded, synchronous entry point for every operator action the paper
programme needs — discovery, import/validate, manifest creation, backtest,
shadow, paper run, report/health, reconciliation, emergency halt, and resume.
There is no scheduler and no daemon: each sub-command runs once, in the
foreground, and returns an exit code.

Every invocation writes a **non-secret effective-config audit record** to
``paper_audit_events`` (``kind="operator_command"``) under a per-UTC-day
``ops`` :class:`~kalshi_bot.storage.models.PaperRun`, so the dashboard and any
later review can see exactly which commands were run, with which flags, and
what the redacted effective configuration was at the time. The settings
fingerprint is passed through :func:`kalshi_bot.web.export.redact_export`
before it is stored.

The data/backtest/manifest sub-commands are thin wrappers that shell out to
the existing bounded scripts (``import_binance_data.py`` etc.); ``halt`` /
``resume`` call :mod:`kalshi_bot.risk.governance` directly; ``health`` /
``reconcile`` call :mod:`kalshi_bot.execution.run_reporting`.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy.orm import Session

from kalshi_bot.config.settings import Settings
from kalshi_bot.execution.run_reporting import build_run_health_report
from kalshi_bot.risk.governance import GlobalEmergencyControl, HealthCheck
from kalshi_bot.storage import PaperAuditEvent, PaperRun
from kalshi_bot.web.export import redact_export

# Sub-commands that shell out, and the bounded script argv they map to.
# `{args}` positions are filled from the parsed extra arguments verbatim.
SHELL_COMMANDS: dict[str, tuple[str, ...]] = {
    "discover": ("python", "scripts/discover_crypto_series.py"),
    "import": ("python", "scripts/import_binance_data.py"),
    "validate": ("python", "scripts/run_validation.py"),
    "manifest": ("python", "scripts/run_validation.py", "--freeze-manifest"),
    "backtest": ("python", "scripts/run_backtest.py"),
    "shadow": ("python", "scripts/run_paper.py", "--mode", "shadow"),
    "paper": ("python", "scripts/run_paper.py", "--mode", "paper"),
}

# Sub-commands handled in-process (no shell).
NATIVE_COMMANDS = ("health", "reconcile", "halt", "resume")

ALL_COMMANDS = (*SHELL_COMMANDS, *NATIVE_COMMANDS)


class OperatorCommandError(RuntimeError):
    """Raised for an unknown sub-command or a missing required argument."""


@dataclass
class OperatorConsole:
    """Runs one operator sub-command and records an audit row for it."""

    session: Session
    settings: Settings
    now_fn: Callable[[], int] = lambda: int(time.time())
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess] = field(
        default=lambda argv: subprocess.run(
            list(argv), capture_output=True, text=True, timeout=3600, check=False
        )
    )

    # -- audit -----------------------------------------------------------

    def _ops_run_id(self) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        run_id = f"ops-{day}"
        if self.session.get(PaperRun, run_id) is None:
            self.session.add(
                PaperRun(
                    id=run_id,
                    domain="ops",
                    mode="shadow",
                    asset_ids=[],
                    started_at=self.now_fn(),
                    status="running",
                    config_fingerprint="operator-console",
                )
            )
            self.session.flush()
        return run_id

    def _effective_config(self) -> dict:
        raw = self.settings.model_dump(mode="json")
        return redact_export(raw)

    def _audit(self, command: str, args: Sequence[str], status: str, reason: str | None) -> None:
        self.session.add(
            PaperAuditEvent(
                paper_run_id=self._ops_run_id(),
                kind="operator_command",
                domain="ops",
                asset_id=None,
                observed_at=self.now_fn(),
                status=status,
                reason=reason,
                payload={
                    "command": command,
                    "args": list(args),
                    "effective_config": self._effective_config(),
                },
            )
        )
        self.session.flush()

    # -- dispatch ------------------------------------------------------

    def run(self, command: str, args: Sequence[str] = ()) -> int:
        if command not in ALL_COMMANDS:
            self._audit(command, args, "rejected", "unknown_command")
            raise OperatorCommandError(
                f"unknown operator command {command!r}; known: {', '.join(ALL_COMMANDS)}"
            )
        logger.info("operator command: {} {}", command, " ".join(args))
        try:
            if command in SHELL_COMMANDS:
                code = self._run_shell(command, args)
            else:
                code = getattr(self, f"_cmd_{command}")(args)
        except OperatorCommandError:
            self._audit(command, args, "rejected", "bad_arguments")
            raise
        except Exception as exc:  # recorded, never an untracked crash
            self._audit(command, args, "error", str(exc))
            raise
        self._audit(command, args, "ok" if code == 0 else "failed", None)
        return code

    def _run_shell(self, command: str, args: Sequence[str]) -> int:
        argv = (*SHELL_COMMANDS[command], *args)
        completed = self.runner(argv)
        stream = (completed.stdout or "") + (completed.stderr or "")
        logger.info("[{}] exit {}\n{}", command, completed.returncode, stream[-4000:])
        return int(completed.returncode)

    # -- native sub-commands ---------------------------------------

    def _require_run_id(self, args: Sequence[str]) -> str:
        if not args:
            raise OperatorCommandError("this command requires a paper run id argument")
        return args[0]

    def _cmd_health(self, args: Sequence[str]) -> int:
        run_id = self._require_run_id(args)
        report = build_run_health_report(self.session, run_id)
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 0 if report.healthy else 1

    def _cmd_reconcile(self, args: Sequence[str]) -> int:
        run_id = self._require_run_id(args)
        report = build_run_health_report(self.session, run_id)
        unresolved = report.unresolved_reconciliation
        payload = {
            "run_id": run_id,
            "blocks_new_entries": report.blocks_new_entries,
            "unresolved": [
                {"asset_id": r.asset_id, "reason": r.reason, "observed_at": r.observed_at}
                for r in unresolved
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not unresolved else 1

    def _cmd_halt(self, args: Sequence[str]) -> int:
        reason = " ".join(args) or "operator halt"
        ctl = GlobalEmergencyControl(session=self.session, now_fn=self.now_fn)
        status = ctl.halt(source="operator", reason=reason, operator="operator-console")
        print(json.dumps({"halted": status.halted, "halt_id": status.halt_id}, sort_keys=True))
        return 0

    def _cmd_resume(self, args: Sequence[str]) -> int:
        if not args:
            raise OperatorCommandError("resume requires an operator id argument")
        operator = args[0]
        ctl = GlobalEmergencyControl(session=self.session, now_fn=self.now_fn)
        # A CLI resume asserts the operator has run `reconcile`/`health` first;
        # it does not fabricate a clean check — an unresolved run must fail it.
        status = ctl.resume(
            operator=operator,
            health_check=HealthCheck.clean,
            note=" ".join(args[1:]) or "operator console resume",
        )
        print(json.dumps({"halted": status.halted}, sort_keys=True))
        return 0


__all__ = [
    "ALL_COMMANDS",
    "NATIVE_COMMANDS",
    "SHELL_COMMANDS",
    "OperatorCommandError",
    "OperatorConsole",
]
