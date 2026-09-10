"""Allowlisted, observable operator jobs launched from the local dashboard."""

from __future__ import annotations

import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

COMMANDS: dict[str, tuple[str, ...]] = {
    "tests": ("uv", "run", "pytest", "-q"),
    "lint": ("uv", "run", "ruff", "check", "src", "tests"),
    "openspec_validate": ("openspec", "validate", "multi-venue-paper-trading"),
    "data_tracker_help": ("uv", "run", "python", "scripts/import_binance_data.py", "--help"),
    "data_tracker_btc": (
        "uv",
        "run",
        "python",
        "scripts/import_binance_data.py",
        "--asset",
        "BTC",
        "--market-type",
        "spot",
        "--interval",
        "1m",
        "--year",
        "2025",
        "--month",
        "1",
        "--timestamp-unit",
        "ms",
    ),
    "paper_help": ("uv", "run", "python", "scripts/run_paper_trading.py", "--help"),
    "backtest_help": ("uv", "run", "python", "scripts/run_backtest.py", "--help"),
    "validation_help": ("uv", "run", "python", "scripts/run_validation.py", "--help"),
    "capture_help": ("uv", "run", "python", "scripts/capture_session.py", "--help"),
    "sports_research_help": (
        "uv",
        "run",
        "python",
        "scripts/research_sports_evidence.py",
        "--help",
    ),
    "sports_discover": ("uv", "run", "python", "scripts/capture_sports.py", "--discover"),
    # Foreground operator hub (multi-venue-paper-trading §12.3): each writes a
    # redacted effective-config audit record under the per-day `ops` run.
    "operate_help": ("uv", "run", "python", "scripts/operate.py", "--help"),
}


@dataclass
class Operation:
    id: str
    name: str
    command: tuple[str, ...]
    status: str = "queued"
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    output: str = ""


@dataclass
class OperationManager:
    root: Path
    jobs: dict[str, Operation] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, name: str) -> Operation:
        if name not in COMMANDS:
            raise KeyError(name)
        with self.lock:
            if any(job.status == "running" and job.name == name for job in self.jobs.values()):
                raise RuntimeError(f"{name} is already running")
            job = Operation(uuid.uuid4().hex[:12], name, COMMANDS[name])
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Operation) -> None:
        with self.lock:
            job.status = "running"
            job.started_at = datetime.now(UTC).isoformat()
        try:
            completed = subprocess.run(
                job.command, cwd=self.root, capture_output=True, text=True, timeout=3600
            )
            job.output = (completed.stdout + completed.stderr)[-20000:]
            job.exit_code = completed.returncode
            job.status = "passed" if completed.returncode == 0 else "failed"
        except Exception as exc:  # operator-visible failure, never an untracked crash
            job.output = str(exc)
            job.status = "failed"
        finally:
            with self.lock:
                job.ended_at = datetime.now(UTC).isoformat()

    def snapshot(self) -> list[Operation]:
        with self.lock:
            return list(reversed(list(self.jobs.values())))


@dataclass
class PaperProcess:
    root: Path
    process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("paper engine is already running")
        self.process = subprocess.Popen(
            ("uv", "run", "python", "scripts/run_paper_trading.py"),
            cwd=self.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def snapshot(self) -> dict[str, object]:
        running = self.process is not None and self.process.poll() is None
        return {"running": running, "pid": self.process.pid if running and self.process else None}


@dataclass
class CaptureProcess(PaperProcess):
    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("capture feeds are already running")
        self.process = subprocess.Popen(
            ("cmd", "/c", "start_capture.bat"),
            cwd=self.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


__all__ = ["COMMANDS", "CaptureProcess", "Operation", "OperationManager", "PaperProcess"]
