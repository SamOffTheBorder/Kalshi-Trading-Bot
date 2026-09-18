import pytest
from scripts.freeze_manifest import build_manifest_spec, freeze_manifest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.manifests import manifest_provenance_class
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import BRTIObservation, DatasetManifest, SpotCandle


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def _spot(session, provenance=None):
    session.add(
        SpotCandle(
            exchange="kraken", symbol="BTC-USD", period_minutes=60, open_ts=100,
            open=1, high=2, low=1, close=2, volume=1, provenance=provenance,
        )
    )


def _brti(session, provenance=None):
    session.add(
        BRTIObservation(
            observed_at=200, available_at=201, value_dollars="100.0",
            source="kalshi:cfbenchmarks/BRTI", provenance=provenance,
        )
    )


def test_freeze_uses_native_partitions_and_is_idempotent(session_factory):
    with session_factory() as session:
        _spot(session)
        _brti(session)
        spec = build_manifest_spec(session, asset_id="BTC", sources=("spot", "brti"))
        first = freeze_manifest(session, spec, created_at=300)
        second = freeze_manifest(session, spec, created_at=999)
        assert first["source_native"] is True
        assert second["reused"] is True
        assert session.query(DatasetManifest).count() == 1
        assert manifest_provenance_class(session.query(DatasetManifest).one()) == "source_native"


def test_freeze_preserves_reconstructed_classification(session_factory):
    with session_factory() as session:
        _brti(session, {"synthetic": True})
        spec = build_manifest_spec(session, asset_id="BTC", sources=("brti",))
        report = freeze_manifest(session, spec, created_at=300)
        assert report["provenance_class"] == "reconstructed"
        assert report["source_native"] is False
