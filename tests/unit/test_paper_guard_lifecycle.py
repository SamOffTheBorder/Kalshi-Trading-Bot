from pathlib import Path

import pytest

from kalshi_bot.config.lifecycle import AssetDomainCandidate, validate_lifecycle
from kalshi_bot.config.settings import Settings
from kalshi_bot.execution.paper_guard import PaperExecutionError, PaperExecutionGuard


def test_authenticated_paper_guard_requires_demo_environment(tmp_path: Path):
    settings = Settings(
        paper_trading=True,
        kalshi_use_demo_env=False,
        db_path=tmp_path / "paper.db",
    )
    with pytest.raises(PaperExecutionError, match="KALSHI_USE_DEMO_ENV"):
        PaperExecutionGuard.validate(settings, mode="paper")


def test_guard_refuses_paper_trading_disabled_even_with_demo_environment(tmp_path: Path):
    settings = Settings(
        paper_trading=False,
        kalshi_use_demo_env=True,
        db_path=tmp_path / "paper.db",
    )
    with pytest.raises(PaperExecutionError, match="PAPER_TRADING"):
        PaperExecutionGuard.validate(settings, mode="paper")


def test_guard_refuses_directory_as_unsafe_ledger_target(tmp_path: Path):
    settings = Settings(paper_trading=True, kalshi_use_demo_env=True, db_path=tmp_path)
    with pytest.raises(PaperExecutionError, match="directory"):
        PaperExecutionGuard.validate(settings, mode="paper")


def test_production_configuration_never_passes_authenticated_paper_guard(tmp_path: Path):
    settings = Settings(
        paper_trading=True,
        kalshi_use_demo_env=False,
        live_trading_confirmation_phrase="I understand this places real orders",
        db_path=tmp_path / "paper.db",
    )
    with pytest.raises(PaperExecutionError, match="KALSHI_USE_DEMO_ENV"):
        PaperExecutionGuard.validate(settings, mode="paper", require_authenticated=True)


def test_public_shadow_guard_can_skip_authenticated_requirement(tmp_path: Path):
    settings = Settings(
        paper_trading=True,
        kalshi_use_demo_env=False,
        db_path=tmp_path / "paper.db",
    )
    guard = PaperExecutionGuard.validate(settings, mode="shadow", require_authenticated=False)
    assert guard.mode == "shadow"
    assert guard.ledger_path == tmp_path / "paper.db"


def test_guard_rejects_non_sqlite_ledger(tmp_path: Path):
    settings = Settings(paper_trading=True, kalshi_use_demo_env=True, db_path=tmp_path / "paper.db")
    with pytest.raises(PaperExecutionError, match="SQLite"):
        PaperExecutionGuard.validate(settings, mode="paper", ledger_path=tmp_path / "ledger.json")


def test_guard_rejects_mutating_adapter():
    class LiveAdapter:
        broker_name = "live"

        def create_order(self):
            pass

    with pytest.raises(PaperExecutionError, match="mutating"):
        PaperExecutionGuard.assert_paper_adapter(LiveAdapter())


def test_lifecycle_identity_and_states():
    identity = AssetDomainCandidate("BTC", "perp", "funding-carry-v1")
    assert identity.key == "BTC:perp:funding-carry-v1"
    assert validate_lifecycle("paper") == "paper"
    with pytest.raises(ValueError):
        validate_lifecycle("live")
    with pytest.raises(ValueError):
        AssetDomainCandidate("btc", "perp", "x")
