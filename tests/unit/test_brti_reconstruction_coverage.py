import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.manifests import ManifestSpec, persist_manifest
from kalshi_bot.storage.db import create_all_tables
from kalshi_bot.storage.models import BRTIObservation, ReconstructedIndexObservation
from kalshi_bot.web.queries import brti_reconstruction_coverage


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    return sessionmaker(bind=engine)


def test_coverage_reports_unmeasured_with_no_manifest(session_factory):
    with session_factory() as session:
        session.add(
            ReconstructedIndexObservation(
                target_index="BRTI",
                observed_at=100,
                value_dollars="50000.00",
                contributor_count=2,
                contributing_venues=["kraken", "coinbase"],
                provenance="reconstructed_index",
                composed_at=200,
                composer_version="synthetic-brti-v1",
            )
        )
        session.commit()
        coverage = brti_reconstruction_coverage(session)
        assert coverage.reconstructed_rows == 1
        assert coverage.captured_rows == 0
        assert coverage.contributing_venues == ["coinbase", "kraken"]
        assert coverage.measurement_status == "unmeasured"


def test_coverage_separates_captured_from_reconstructed_counts(session_factory):
    with session_factory() as session:
        session.add(
            BRTIObservation(
                observed_at=100, available_at=100, value_dollars="50000.00", source="cf"
            )
        )
        session.add(
            ReconstructedIndexObservation(
                target_index="BRTI",
                observed_at=100,
                value_dollars="50010.00",
                contributor_count=1,
                contributing_venues=["kraken"],
                provenance="reconstructed_index",
                composed_at=200,
                composer_version="synthetic-brti-v1",
            )
        )
        session.commit()
        coverage = brti_reconstruction_coverage(session)
        assert coverage.captured_rows == 1
        assert coverage.reconstructed_rows == 1


def test_coverage_reports_measured_when_the_latest_manifest_has_a_measurement(session_factory):
    with session_factory() as session:
        spec = ManifestSpec(
            asset_ids=("BTC",),
            source_ids=("a" * 64,),
            start_ts=0,
            end_ts=100,
            parser_version="p1",
            feature_version="f1",
            code_revision="r1",
            config_sha256="c" * 64,
            reconstruction_error={"status": "measured", "resolution_agreement": 0.6},
        )
        persist_manifest(session, spec, created_at=300)
        session.commit()
        coverage = brti_reconstruction_coverage(session)
        assert coverage.measurement_status == "measured"
