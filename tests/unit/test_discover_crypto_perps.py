import pytest
from scripts.discover_crypto_perps import run_discovery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.config.crypto_registry import DEFAULT_CRYPTO_REGISTRY
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import DiscoveryResult


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


class FakeMarginClient:
    def get_market(self, ticker):
        asset = ticker.removeprefix("KX").removesuffix("PERP")
        return {
            "status": "active", "multiplier": "1", "min_order_size": "0.01",
            "reference_index": "BRTI" if asset == "BTC" else f"{asset}USD_RTI",
            "updated_at": 100,
        }


def test_perp_discovery_persists_one_eligible_row_per_asset(session_factory):
    with session_factory() as session:
        rows = run_discovery(
            FakeMarginClient(), session, DEFAULT_CRYPTO_REGISTRY, clock=lambda: 100
        )
        assert len(rows) == 4
        assert all(row["eligible"] for row in rows)
        assert session.query(DiscoveryResult).filter_by(instrument="perp").count() == 4
