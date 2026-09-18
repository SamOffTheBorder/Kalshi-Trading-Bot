import pytest
from scripts.run_paper import _build_adapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.config.settings import Settings
from kalshi_bot.execution.sports_paper import SportsPaperAdapter
from kalshi_bot.storage.db import create_all_tables


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def test_build_adapter_wires_sports_without_bypassing_admission(session_factory):
    adapter = _build_adapter(
        "sports", session_factory, Settings(), strategy_id="hold", run_id="test-run"
    )
    try:
        assert isinstance(adapter, SportsPaperAdapter)
        decision = adapter.evaluate("BTC", now_ts=100, may_fill=True)
        assert decision.reason == "research_not_promising"
    finally:
        adapter.session.close()
