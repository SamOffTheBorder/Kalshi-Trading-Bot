## ADDED Requirements

### Requirement: External evidence is attributable and point-in-time
Every imported sports evidence card SHALL include provider, endpoint or URL,
observed or publication time, local availability time, retrieval time, raw
content hash, and extracted claims.

#### Scenario: Evidence lacks causal timing
- **WHEN** an adapter cannot establish when information was published or
  observed
- **THEN** the observation is rejected from validation and recorded as
  unusable evidence

### Requirement: Evidence sources are opt-in and allowlisted
External evidence SHALL be disabled by default and SHALL only be retrieved by
an explicitly configured adapter whose provider and domains are allowlisted.

#### Scenario: Unconfigured source is requested
- **WHEN** a validation run has no configured evidence adapter
- **THEN** it runs on Kalshi-derived inputs only and makes no external request

### Requirement: Evidence history is append-only
Evidence cards SHALL retain raw hashes and conflicting claims as separate
versions; later retrieval SHALL not overwrite an earlier card.

#### Scenario: Source changes a lineup claim
- **WHEN** the same source later returns different content
- **THEN** a new version is stored and the validation run can identify which
  version was available at its decision time
