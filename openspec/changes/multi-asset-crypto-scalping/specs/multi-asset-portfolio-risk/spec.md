## ADDED Requirements

### Requirement: Hierarchical multi-asset admission controls
Before sizing a crypto entry, the system SHALL enforce global emergency and
daily-loss controls, a crypto portfolio gross-risk limit, a correlation-group
limit, a per-asset limit, and the existing per-position fixed-risk/exchange
limits, in that order. Assets MUST NOT be sized as independent full bankrolls.

#### Scenario: Correlated entries arrive together
- **WHEN** two assets in the same correlation group produce entry decisions that would exceed the group limit in aggregate
- **THEN** the first admissible entry MAY proceed within all limits and later entries SHALL be rejected or reduced according to the configured group budget

### Requirement: Conservative default correlation grouping
All enabled crypto assets SHALL belong to a correlation group. BTC, ETH, SOL,
XRP, DOGE, BNB, HYPE, NEAR, ZEC, and LINK SHALL initially share one
`major-crypto` group unless an explicitly configured and documented replacement
grouping is validated.

#### Scenario: Asset lacks a correlation group
- **WHEN** an asset becomes eligible for an entry without a configured correlation group
- **THEN** the system SHALL fail closed and record `missing_correlation_group` as the admission reason

### Requirement: Asset-level risk audit trail
The system SHALL persist the asset ID, correlation group, limits evaluated,
requested size, admitted size, and rejection reason for each evaluated entry
that reaches portfolio admission.

#### Scenario: Operator reviews a rejected trade
- **WHEN** an entry is blocked by a portfolio or asset cap
- **THEN** the dashboard and audit record SHALL identify the blocking level and current applicable exposure

