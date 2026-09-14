from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kalshi_bot.data.manifests import (
    ManifestError,
    ManifestSpec,
    classify_provenance,
    manifest_hash,
    manifest_provenance_class,
    persist_manifest,
    validate_manifest,
)
from kalshi_bot.storage.db import create_all_tables


def _spec() -> ManifestSpec:
    return ManifestSpec(
        asset_ids=("XRP", "BTC"),
        source_ids=("b" * 64, "a" * 64),
        start_ts=100,
        end_ts=200,
        parser_version="p1",
        feature_version="f1",
        code_revision="r1",
        config_sha256="c" * 64,
        filter_rules={"complete_only": True},
    )


def test_manifest_hash_is_canonical_and_persistence_is_idempotent(tmp_path: Path):
    assert manifest_hash(_spec()) == manifest_hash(
        ManifestSpec(**{**_spec().__dict__, "asset_ids": ("BTC", "XRP")})
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    create_all_tables(engine)
    with sessionmaker(bind=engine)() as session:
        first = persist_manifest(session, _spec(), created_at=300)
        second = persist_manifest(session, _spec(), created_at=999)
        assert first.id == second.id
        session.commit()


def test_manifest_validation_fails_closed_for_missing_or_rejected_sources():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with sessionmaker(bind=engine)() as session:
        row = persist_manifest(session, _spec(), created_at=300)
        with pytest.raises(ManifestError, match="unavailable"):
            validate_manifest(row, available_source_ids={"a" * 64})
        with pytest.raises(ManifestError, match="rejected"):
            validate_manifest(
                row,
                available_source_ids={"a" * 64, "b" * 64},
                rejected_source_ids={"b" * 64},
            )


def test_manifest_pins_partitions_and_blocks_revisions_or_misalignment():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    spec = ManifestSpec(
        **{
            **_spec().__dict__,
            "artifact_hashes": ("a" * 64, "b" * 64),
            "normalized_partitions": ("BTC:spot:1m:100-200",),
            "source_mappings": {"BTC": "BTCUSDT"},
        }
    )
    with sessionmaker(bind=engine)() as session:
        row = persist_manifest(session, spec, created_at=300)
        assert row.artifact_hashes == ["a" * 64, "b" * 64]
        with pytest.raises(ManifestError, match="configuration"):
            validate_manifest(
                row, available_source_ids=set(row.source_ids), expected_config_sha256="x" * 64
            )
        with pytest.raises(ManifestError, match="partitions"):
            validate_manifest(
                row, available_source_ids=set(row.source_ids), required_partitions={"ETH:spot:1m"}
            )
        with pytest.raises(ManifestError, match="aligned"):
            validate_manifest(row, available_source_ids=set(row.source_ids), source_aligned=False)


def test_classify_provenance_is_fail_closed():
    # All partitions source-native -> source_native.
    assert classify_provenance({"a": "source_native", "b": "source_native"}) == "source_native"
    # A mixed manifest classifies reconstructed.
    assert classify_provenance({"a": "source_native", "b": "reconstructed"}) == "reconstructed"
    # An unrecognized provenance value classifies reconstructed, not
    # source_native.
    assert classify_provenance({"a": "source_native", "b": "made_up"}) == "reconstructed"
    # No partitions declared at all classifies reconstructed.
    assert classify_provenance({}) == "reconstructed"


def test_persisted_manifest_provenance_class_defaults_to_reconstructed():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with sessionmaker(bind=engine)() as session:
        # A manifest constructed without partition_provenance must not be
        # admissible: it classifies reconstructed, not source_native.
        row = persist_manifest(session, _spec(), created_at=300)
        assert row.provenance_class == "reconstructed"
        assert manifest_provenance_class(row) == "reconstructed"


def test_persisted_manifest_provenance_class_source_native_requires_all_partitions():
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    mixed_spec = ManifestSpec(
        **{
            **_spec().__dict__,
            "partition_provenance": {
                "BTC:kraken:1s": "source_native",
                "BTC:reconstructed_index:1s": "reconstructed",
            },
        }
    )
    all_native_spec = ManifestSpec(
        **{
            **_spec().__dict__,
            "partition_provenance": {
                "BTC:kraken:1s": "source_native",
                "ETH:kraken:1s": "source_native",
            },
        }
    )
    with sessionmaker(bind=engine)() as session:
        mixed_row = persist_manifest(session, mixed_spec, created_at=300)
        assert manifest_provenance_class(mixed_row) == "reconstructed"

        native_row = persist_manifest(session, all_native_spec, created_at=301)
        assert manifest_provenance_class(native_row) == "source_native"


def test_manifest_provenance_class_treats_unset_field_as_reconstructed():
    """Direct test of the default-on-omission read path (tasks.md 1.5): a
    manifest row lacking `provenance_class` must not be admissible."""
    engine = create_engine("sqlite://")
    create_all_tables(engine)
    with sessionmaker(bind=engine)() as session:
        row = persist_manifest(session, _spec(), created_at=300)
        row.provenance_class = None
        assert manifest_provenance_class(row) == "reconstructed"
