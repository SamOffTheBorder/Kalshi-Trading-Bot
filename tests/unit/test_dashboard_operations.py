from pathlib import Path
from subprocess import CompletedProcess

from kalshi_bot.web.operations import COMMANDS, Operation, OperationManager


def test_operation_manager_uses_only_allowlisted_commands(tmp_path: Path):
    manager = OperationManager(tmp_path)
    assert "tests" in COMMANDS
    assert manager.get("missing") is None
    try:
        manager.start("not-allowlisted")
    except KeyError:
        pass
    else:
        raise AssertionError("unallowlisted command was accepted")


def test_operation_history_survives_dashboard_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "kalshi_bot.web.operations.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "1006 passed", ""),
    )
    history = tmp_path / "job-history.json"
    manager = OperationManager(tmp_path, history_path=history)
    job = Operation("job123", "tests", COMMANDS["tests"])
    manager.jobs[job.id] = job
    manager._run(job)

    restored = OperationManager(tmp_path, history_path=history).get("job123")
    assert restored is not None
    assert restored.status == "passed"
    assert restored.output == "1006 passed"
