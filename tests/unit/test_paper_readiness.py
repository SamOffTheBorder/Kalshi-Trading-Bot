import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.web.queries import papertrading_readiness


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def test_readiness_matrix_exposes_sports_report_as_absent(session_factory):
    with session_factory() as session:
        rows = papertrading_readiness(session, now_ts=1_000)
        btc = next(row for row in rows if row.domain == "prediction" and row.asset_id == "BTC")
        sports = next(row for row in rows if row.domain == "sports")
        assert btc.lifecycle == "shadow"
        assert btc.manifest_frozen is False
        assert sports.cli_wired is True
        assert sports.feasibility_outcome == "absent"
        assert sports.ready is False
