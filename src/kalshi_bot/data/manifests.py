"""Immutable dataset manifest creation and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from kalshi_bot.storage.models import DatasetManifest


class ManifestError(ValueError):
    """Raised when a frozen manifest cannot be created or safely reused."""


_SOURCE_NATIVE = "source_native"
_RECONSTRUCTED = "reconstructed"
_RECOGNIZED_PARTITION_PROVENANCE = frozenset({_SOURCE_NATIVE, _RECONSTRUCTED})


def classify_provenance(partition_provenance: dict[str, str]) -> str:
    """Fail-closed manifest classification (brti-constituent-history §D5).

    A manifest is ``source_native`` only when every partition it enumerates
    is declared ``source_native``. A manifest with no partitions declared, an
    unrecognized provenance value, or any ``reconstructed`` partition is
    ``reconstructed`` -- forgetting to classify a partition blocks promotion
    rather than permitting it.
    """
    if not partition_provenance:
        return _RECONSTRUCTED
    values = set(partition_provenance.values())
    if values <= {_SOURCE_NATIVE}:
        return _SOURCE_NATIVE
    return _RECONSTRUCTED


def idempotency_key(
    source_id: str,
    native_id: str,
    observed_at: int,
    provider_revision: str,
    parser_version: str,
) -> str:
    """Stable key separating provider revisions and parser interpretations."""
    payload = "|".join((source_id, native_id, str(observed_at), provider_revision, parser_version))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ManifestSpec:
    asset_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    start_ts: int
    end_ts: int
    parser_version: str
    feature_version: str
    code_revision: str
    config_sha256: str
    filter_rules: dict[str, object] = field(default_factory=dict)
    coverage_summary: dict[str, object] = field(default_factory=dict)
    artifact_hashes: tuple[str, ...] = ()
    normalized_partitions: tuple[str, ...] = ()
    source_mappings: dict[str, object] = field(default_factory=dict)
    partition_provenance: dict[str, str] = field(default_factory=dict)
    reconstruction_error: dict[str, object] | None = None

    def canonical_payload(self) -> dict[str, object]:
        if self.start_ts >= self.end_ts:
            raise ManifestError("manifest start_ts must precede end_ts")
        if not self.asset_ids or not self.source_ids:
            raise ManifestError("manifest requires at least one asset and source")
        return {
            "asset_ids": sorted(set(self.asset_ids)),
            "source_ids": sorted(set(self.source_ids)),
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "parser_version": self.parser_version,
            "feature_version": self.feature_version,
            "code_revision": self.code_revision,
            "config_sha256": self.config_sha256,
            "filter_rules": self.filter_rules,
            "coverage_summary": self.coverage_summary,
            "artifact_hashes": sorted(set(self.artifact_hashes or self.source_ids)),
            "normalized_partitions": sorted(set(self.normalized_partitions)),
            "source_mappings": self.source_mappings,
            "partition_provenance": dict(sorted(self.partition_provenance.items())),
            "reconstruction_error": self.reconstruction_error,
        }


def manifest_hash(spec: ManifestSpec) -> str:
    payload = json.dumps(spec.canonical_payload(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def persist_manifest(session: Session, spec: ManifestSpec, *, created_at: int) -> DatasetManifest:
    """Insert or return an identical frozen manifest; never mutate one."""

    digest = manifest_hash(spec)
    existing = session.scalar(
        select(DatasetManifest).where(DatasetManifest.manifest_sha256 == digest)
    )
    if existing is not None:
        return existing
    payload = spec.canonical_payload()
    row = DatasetManifest(
        manifest_sha256=digest,
        created_at=created_at,
        asset_ids=payload["asset_ids"],
        source_ids=payload["source_ids"],
        start_ts=spec.start_ts,
        end_ts=spec.end_ts,
        parser_version=spec.parser_version,
        feature_version=spec.feature_version,
        code_revision=spec.code_revision,
        config_sha256=spec.config_sha256,
        filter_rules=spec.filter_rules,
        coverage_summary=spec.coverage_summary,
        artifact_hashes=payload["artifact_hashes"],
        normalized_partitions=payload["normalized_partitions"],
        source_mappings=payload["source_mappings"],
        status="frozen",
        provenance_class=classify_provenance(spec.partition_provenance),
        reconstruction_error=spec.reconstruction_error,
    )
    session.add(row)
    session.flush()
    return row


def manifest_provenance_class(manifest: DatasetManifest) -> str:
    """Read back a manifest's provenance class, fail-closed on omission.

    A manifest persisted before this field existed, or otherwise missing the
    value, is treated as ``reconstructed`` rather than assumed safe.
    """
    value = manifest.provenance_class
    if value not in _RECOGNIZED_PARTITION_PROVENANCE:
        return _RECONSTRUCTED
    return value


def validate_manifest(
    manifest: DatasetManifest,
    *,
    available_source_ids: set[str],
    rejected_source_ids: set[str] | None = None,
    expected_config_sha256: str | None = None,
    required_partitions: set[str] | None = None,
    source_aligned: bool = True,
) -> None:
    """Verify all source IDs in a frozen manifest are still unchanged/usable."""

    rejected = rejected_source_ids or set()
    required = set(manifest.source_ids)
    missing = required - available_source_ids
    if missing:
        raise ManifestError(f"manifest sources unavailable: {sorted(missing)}")
    rejected_required = required & rejected
    if rejected_required:
        raise ManifestError(f"manifest sources rejected: {sorted(rejected_required)}")
    if manifest.status != "frozen":
        raise ManifestError(f"manifest is not frozen: {manifest.status!r}")
    if expected_config_sha256 is not None and manifest.config_sha256 != expected_config_sha256:
        raise ManifestError("manifest configuration hash changed")
    if required_partitions and not required_partitions <= set(manifest.normalized_partitions or []):
        raise ManifestError("manifest normalized partitions unavailable")
    if not source_aligned:
        raise ManifestError("manifest sources are not aligned")


__all__ = [
    "ManifestError",
    "ManifestSpec",
    "classify_provenance",
    "idempotency_key",
    "manifest_hash",
    "manifest_provenance_class",
    "persist_manifest",
    "validate_manifest",
]
