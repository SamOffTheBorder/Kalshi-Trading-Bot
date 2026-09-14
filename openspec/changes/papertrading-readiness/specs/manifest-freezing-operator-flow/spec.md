# Manifest freezing operator flow

## ADDED Requirements

### Requirement: An operator can freeze a manifest without hand-writing one

The system SHALL provide a script that constructs a `ManifestSpec` from
currently captured data for a named asset and source set, and persists it
via the existing `persist_manifest` path. The script SHALL NOT fabricate
provenance: `partition_provenance` SHALL be computed from the actual source
of each queried partition, not assumed.

#### Scenario: Freezing from source-native captured data
- **WHEN** the freeze script runs for an asset whose queried data is entirely
  source-native
- **THEN** a `DatasetManifest` row is persisted with `provenance_class ==
  "source_native"`

#### Scenario: Freezing from partially reconstructed data does not lie
- **WHEN** the freeze script runs for an asset with at least one
  reconstructed partition
- **THEN** a `DatasetManifest` row is persisted with `provenance_class !=
  "source_native"`
- **AND** the script exits successfully, since freezing is a provenance
  record, not a fill-eligibility claim

### Requirement: Freezing is idempotent

Running the freeze script twice with identical inputs SHALL NOT create a
duplicate `DatasetManifest` row; it SHALL return the existing row, matching
`persist_manifest`'s existing hash-based deduplication.

#### Scenario: Re-running with unchanged captured data
- **WHEN** the freeze script runs twice with the same asset, source set, and
  underlying captured data
- **THEN** only one `DatasetManifest` row exists after both runs
