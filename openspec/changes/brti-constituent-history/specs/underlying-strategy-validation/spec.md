## ADDED Requirements

### Requirement: Fail-closed manifest provenance classification
Every dataset manifest SHALL carry a provenance classification of `source_native` or `reconstructed`. A manifest SHALL be classified `source_native` only when every partition it enumerates is source-native. A manifest enumerating any reconstructed partition, any partition whose provenance cannot be determined, or any partition whose provenance is unrecognized SHALL be classified `reconstructed`. A manifest with no classification recorded SHALL be treated as `reconstructed` until classified.

#### Scenario: Manifest mixes source-native and reconstructed partitions
- **WHEN** a manifest enumerates Kraken source-native partitions and one reconstructed index partition
- **THEN** the manifest SHALL be classified `reconstructed`

#### Scenario: A partition has unrecognized provenance
- **WHEN** a manifest enumerates a partition whose provenance value is not recognized
- **THEN** the manifest SHALL be classified `reconstructed` rather than defaulting to `source_native`

### Requirement: Reconstructed manifests are diagnostic-only
A run executed against a `reconstructed` manifest SHALL be reported as diagnostic-only. A diagnostic-only run SHALL be permitted to train models, execute walk-forward research, and produce negative or falsifying results that are actionable on their own. A diagnostic-only run SHALL NOT satisfy an admission report, SHALL NOT advance an asset's lifecycle state, and SHALL NOT be presented as evidence that a strategy has met a promotion criterion. A positive result from a diagnostic-only run SHALL be reported with an explicit status indicating it requires validation against captured index data.

#### Scenario: A strategy loses on reconstructed history
- **WHEN** a walk-forward run on a `reconstructed` manifest fails the promotion bar
- **THEN** the result SHALL be actionable as a rejection and MAY be used to eliminate the strategy

#### Scenario: A strategy wins on reconstructed history
- **WHEN** a walk-forward run on a `reconstructed` manifest clears the promotion bar
- **THEN** the system SHALL report it as diagnostic-only pending captured-index validation and SHALL NOT record a satisfied promotion criterion

### Requirement: Paper admission refuses reconstructed evidence
Paper-run preflight SHALL refuse a frozen admission report whose underlying manifest is classified `reconstructed`, with an explicit reason identifying reconstructed data as inadmissible. An asset whose admission report is refused for this reason SHALL still be admitted for decision recording, so that shadow research continues; only the creation of simulated fills SHALL be refused.

#### Scenario: Frozen report is backed by reconstructed data
- **WHEN** a paper run is started in paper mode for an asset whose frozen admission report references a `reconstructed` manifest
- **THEN** preflight SHALL refuse fills for that asset with a reconstructed-data reason and SHALL admit it for decision recording only

#### Scenario: Frozen report is backed by source-native data
- **WHEN** a frozen admission report references a `source_native` manifest and all other admission conditions hold
- **THEN** preflight SHALL permit fills for that asset

### Requirement: Reconstruction error is recorded with the run
A run executed against a manifest containing reconstructed partitions SHALL record the reconstruction-error measurement associated with those partitions, including the resolution-agreement metric, or SHALL record that the reconstruction is unmeasured. A run report SHALL NOT omit this field, and an unmeasured reconstruction SHALL NOT be reported as a passing quality result.

#### Scenario: Run uses a measured reconstruction
- **WHEN** a diagnostic-only run completes against a reconstruction with a recorded resolution-agreement measurement
- **THEN** the run report SHALL include that measurement

#### Scenario: Run uses an unmeasured reconstruction
- **WHEN** a diagnostic-only run completes against a reconstruction with no overlapping captured index data
- **THEN** the run report SHALL record the reconstruction as unmeasured
