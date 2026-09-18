"""Allowlisted, observable operator jobs launched from the local dashboard."""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
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

MAX_SAVED_JOBS = 100
MAX_OUTPUT_CHARS = 1_000_000


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
    history_path: Path | None = None

    def __post_init__(self) -> None:
        if self.history_path is None:
            self.history_path = self.root / "data" / "dashboard_operations.json"
        self._load()

    def _load(self) -> None:
        if self.history_path is None or not self.history_path.exists():
            return
        try:
            payload = json.loads(self.history_path.read_text(encoding="utf-8"))
            for raw in payload.get("jobs", []):
                job = Operation(**raw)
                # A dashboard restart means an in-memory worker cannot still be observed.
                if job.status in {"queued", "running"}:
                    job.status = "interrupted"
                    job.ended_at = datetime.now(UTC).isoformat()
                    job.output += "\nDashboard restarted before this job reported completion."
                self.jobs[job.id] = job
        except (OSError, TypeError, ValueError):
            # A damaged history file must never prevent the operator UI from starting.
            self.jobs = {}

    def _save_locked(self) -> None:
        if self.history_path is None:
            return
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        recent = list(self.jobs.values())[-MAX_SAVED_JOBS:]
        payload = {"schema_version": 1, "jobs": [asdict(job) for job in recent]}
        temporary = self.history_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.history_path)

    def start(self, name: str) -> Operation:
        if name not in COMMANDS:
            raise KeyError(name)
        with self.lock:
            if any(job.status == "running" and job.name == name for job in self.jobs.values()):
                raise RuntimeError(f"{name} is already running")
            job = Operation(uuid.uuid4().hex[:12], name, COMMANDS[name])
            self.jobs[job.id] = job
            self._save_locked()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Operation) -> None:
        with self.lock:
            job.status = "running"
            job.started_at = datetime.now(UTC).isoformat()
            self._save_locked()
        try:
            completed = subprocess.run(
                job.command, cwd=self.root, capture_output=True, text=True, timeout=3600
            )
            output = (completed.stdout + completed.stderr)[-MAX_OUTPUT_CHARS:]
            exit_code = completed.returncode
            status = "passed" if completed.returncode == 0 else "failed"
        except Exception as exc:  # operator-visible failure, never an untracked crash
            output = str(exc)
            exit_code = None
            status = "failed"
        with self.lock:
            job.output = output
            job.exit_code = exit_code
            job.status = status
            job.ended_at = datetime.now(UTC).isoformat()
            self._save_locked()

    def snapshot(self) -> list[Operation]:
        with self.lock:
            return list(reversed(list(self.jobs.values())))

    def get(self, job_id: str) -> Operation | None:
        """Return one allowlisted job so its captured output can be downloaded."""
        with self.lock:
            return self.jobs.get(job_id)


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
