"""Foreground operator command hub (multi-venue-paper-trading §12.3).

Covers: unknown command rejected; every invocation writes a redacted
effective-config audit row under a per-day `ops` run; shell sub-commands
dispatch the bounded script argv and pass exit codes through; `health` /
`reconcile` read the run-health report; `halt` / `resume` drive the durable
emergency-control state and `resume` refuses without an operator.
"""

from __future__ import annotations

import subprocess

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kalshi_bot.config.settings import Settings
from kalshi_bot.execution.operator_cli import OperatorCommandError, OperatorConsole
from kalshi_bot.storage import Base, EmergencyHaltRecord, PaperAuditEvent, PaperRun


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _settings(**overrides) -> Settings:
    base = dict(paper_trading=True, kalshi_use_demo_env=True, db_path="paper.db")
    base.update(overrides)
    return Settings(**base)


class _FakeRunner:
    def __init__(self, code: int = 0):
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), self.code, stdout="ok\n", stderr="")


def _console(session, *, clock=None, runner=None) -> OperatorConsole:
    counter = iter(range(1_000, 10_000))
    return OperatorConsole(
        session=session,
        settings=_settings(),
        now_fn=(clock or (lambda: next(counter))),
        runner=runner or _FakeRunner(),
    )


def _audit_rows(session) -> list[PaperAuditEvent]:
    return list(
        session.execute(
            select(PaperAuditEvent).where(PaperAuditEvent.kind == "operator_command")
        ).scalars()
    )


def _run(session, run_id="r", domain="prediction", status="completed") -> None:
    session.add(
        PaperRun(
            id=run_id,
            domain=domain,
            mode="paper",
            asset_ids=["BTC"],
            started_at=1,
            ended_at=2,
            status=status,
            config_fingerprint="x",
        )
    )
    session.flush()


def test_unknown_command_is_rejected_and_audited(session):
    console = _console(session)
    with pytest.raises(OperatorCommandError):
        console.run("frobnicate")
    rows = _audit_rows(session)
    assert len(rows) == 1
    assert rows[0].status == "rejected"


def test_shell_command_dispatches_bounded_argv_and_passes_exit_code(session):
    runner = _FakeRunner(code=0)
    console = _console(session, runner=runner)
    code = console.run("import", ["--asset", "BTC"])
    assert code == 0
    assert runner.calls == [
        ["python", "scripts/import_binance_data.py", "--asset", "BTC"]
    ]
    rows = _audit_rows(session)
    assert rows[0].status == "ok"
    assert rows[0].payload["command"] == "import"
    assert rows[0].payload["args"] == ["--asset", "BTC"]


def test_failing_shell_command_records_failed(session):
    console = _console(session, runner=_FakeRunner(code=3))
    assert console.run("backtest") == 3
    assert _audit_rows(session)[0].status == "failed"


def test_effective_config_is_redacted_in_the_audit_row(session):
    console = _console(session)
    console.run("discover")
    cfg = _audit_rows(session)[0].payload["effective_config"]
    # a private-key path key is redacted, a plain flag is preserved
    joined = str(cfg)
    assert "[REDACTED]" in joined
    assert cfg["paper_trading"] is True


def test_ops_run_is_reused_not_duplicated(session):
    console = _console(session)
    console.run("discover")
    console.run("validate")
    ops_runs = list(
        session.execute(select(PaperRun).where(PaperRun.domain == "ops")).scalars()
    )
    assert len(ops_runs) == 1
    assert len(_audit_rows(session)) == 2


def test_health_reports_healthy_run(session):
    _run(session)
    session.add(
        PaperAuditEvent(
            paper_run_id="r",
            kind="decision",
            domain="prediction",
            asset_id="BTC",
            observed_at=5,
            status="hold",
            payload={},
        )
    )
    session.flush()
    assert _console(session).run("health", ["r"]) == 0


def test_reconcile_returns_nonzero_when_unresolved(session):
    _run(session)
    session.add(
        PaperAuditEvent(
            paper_run_id="r",
            kind="reconciliation",
            domain="prediction",
            asset_id="BTC",
            observed_at=5,
            status="reconciliation_required",
            reason="orphan",
            payload={},
        )
    )
    session.flush()
    assert _console(session).run("reconcile", ["r"]) == 1


def test_health_requires_a_run_id(session):
    with pytest.raises(OperatorCommandError):
        _console(session).run("health")


def test_halt_and_resume_drive_the_durable_state(session):
    console = _console(session)
    assert console.run("halt", ["market", "data", "gap"]) == 0
    assert session.query(EmergencyHaltRecord).count() == 1
    assert console.run("resume", ["alice", "checked"]) == 0
    actions = [
        r.action
        for r in session.execute(
            select(EmergencyHaltRecord).order_by(EmergencyHaltRecord.id)
        ).scalars()
    ]
    assert actions == ["halt", "resume"]


def test_resume_requires_an_operator_argument(session):
    console = _console(session)
    console.run("halt")
    with pytest.raises(OperatorCommandError):
        console.run("resume")
