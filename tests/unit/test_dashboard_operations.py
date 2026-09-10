from pathlib import Path

from kalshi_bot.web.operations import COMMANDS, OperationManager


def test_operation_manager_uses_only_allowlisted_commands(tmp_path: Path):
    manager = OperationManager(tmp_path)
    assert "tests" in COMMANDS
    try:
        manager.start("not-allowlisted")
    except KeyError:
        pass
    else:
        raise AssertionError("unallowlisted command was accepted")
