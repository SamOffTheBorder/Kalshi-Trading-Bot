## ADDED Requirements

### Requirement: Explicit odds-provider admission
The system SHALL define an `OddsProvider` boundary supporting manual/imported inputs, deterministic mocks, and optional provider adapters. No external provider SHALL become active until explicitly configured and admitted with coverage, terms, cost, entitlement, rate-limit, retention, and historical-data constraints recorded. Provider keys SHALL remain server-side in `Settings` and excluded from browser payloads, logs, exports, and raw request audit. This capability SHALL require no paid subscription by default.

#### Scenario: No commercial provider is configured
- **WHEN** an operator uses the initial scanner installation
- **THEN** manual/imported and mock workflows remain available and no paid provider request or purchase occurs

#### Scenario: API key exists without provider admission
- **WHEN** credentials are present but source approval or required entitlement is absent
- **THEN** the provider remains ineligible for automated scanning with an explicit configuration reason

### Requirement: Causal two-sided sportsbook snapshots
Every odds observation SHALL preserve provider and distinct sportsbook identity, external fixture ID, stable shared IDs where available, sport, league, participants and home/away orientation, scheduled start, market type, outcome definitions, decimal or source-native odds, source time, available time, retrieval time, and raw provenance. Imports SHALL record manual origin and original timestamp; import time MUST NOT replace an unknown observation time. Only observations known at the scan cutoff SHALL participate.

#### Scenario: Old odds are imported today
- **WHEN** a file contains an old source timestamp or no verifiable source timestamp
- **THEN** the import is labeled manual and its odds do not qualify as fresh because of today's import time

#### Scenario: Same book appears through two feeds
- **WHEN** two providers supply prices for the same underlying sportsbook
- **THEN** the system counts that sportsbook once using a deterministic documented observation-selection rule

### Requirement: Deterministic vig-free consensus
An eligible consensus SHALL contain at least three distinct admitted sportsbooks with fresh prices for both sides of the same compatible two-outcome moneyline. Each book's implied probabilities SHALL be normalized by their sum to remove overround before aggregation. The default aggregation SHALL be the arithmetic mean of accepted per-book vig-free probabilities; alternative configured methods SHALL be versioned and replayable. The result SHALL retain included/excluded books, odds, freshness decisions, weights, algorithm version, source count, and dispersion. A single book, one-sided feed, third-party model, or unmodeled three-way outcome MUST NOT be labeled consensus.

#### Scenario: Three fresh two-sided books agree on market definition
- **WHEN** three distinct admitted books provide valid paired odds before the cutoff
- **THEN** consensus is the recorded deterministic aggregate of individually de-vigged probabilities and includes all three source identities

#### Scenario: Third book has one stale side
- **WHEN** only two books have fresh complete pairs and a third has a stale or missing side
- **THEN** the result is insufficient consensus and cannot qualify an automated candidate

#### Scenario: Soccer fixture includes draw
- **WHEN** available odds describe a three-way home/draw/away market and the implementation only models two outcomes
- **THEN** the market is rejected as an unsupported settlement shape without renormalizing away the draw

### Requirement: Auditable event matching
The matcher SHALL prefer exact shared stable event IDs, including `sportradarGameId`, while checking for contradictory event metadata. Where shared IDs are absent it SHALL use versioned participant normalization/aliases, league, scheduled-start tolerance, home/away orientation, and market type. It SHALL emit a confidence grade and retain every input, candidate match, score/reason, algorithm version, and selected or rejected identity. Similar names alone SHALL never establish equivalence.

#### Scenario: Shared ID conflicts with league or participants
- **WHEN** equal shared IDs accompany incompatible event metadata
- **THEN** the match is blocked and routed for review rather than accepted solely on the ID

#### Scenario: Two fixtures share participant names
- **WHEN** fallback matching yields multiple plausible fixtures such as a doubleheader
- **THEN** the decision remains ambiguous and no fixture is automatically selected for ranking

### Requirement: Settlement-rule equivalence and review queue
Event identity SHALL be necessary but insufficient for market equivalence. The system SHALL compare outcome and side orientation, game period, overtime inclusion, draw treatment, cancellation/postponement/void rules, resolution source, and other material settlement terms. Unknown, incompatible, or low-confidence joins SHALL enter a manual-review queue and be excluded from automated ranking. Review decisions SHALL preserve actor, timestamp, reason, prior decision, and evidence; approval SHALL not bypass freshness, source-count, cost, or liquidity gates and SHALL be invalidated when material event/rule inputs change.

#### Scenario: Same event has regulation-only and overtime-inclusive prices
- **WHEN** a venue market and sportsbook market differ in overtime treatment
- **THEN** they are incompatible and no consensus for one is applied to the other

#### Scenario: Operator resolves an alias ambiguity
- **WHEN** an authorized reviewer records a supported participant mapping
- **THEN** the system retains the review evidence and reevaluates every remaining eligibility gate before admitting the match

#### Scenario: Approved mapping changes after postponement
- **WHEN** start time or settlement rules change materially after manual approval
- **THEN** the previous approval is marked stale and the match requires reevaluation

### Requirement: Consensus and matching acceptance evidence
Phase 3 admission SHALL require deterministic known-answer odds/vig tests and fixtures for duplicate books, missing sides, stale/future/unavailable observations, source conflicts, ID contradictions, alias collisions, timezones, postponements, doubleheaders, draws, overtime, and manual-review invalidation. Historical evaluation SHALL preserve chronological cutoffs and holdout provenance from existing sports research. New consensus output SHALL not establish a paper or live promotion decision.

#### Scenario: Historical data would leak a later update
- **WHEN** replay finds an odds update or match decision unavailable at the historical cutoff
- **THEN** it excludes that update and records the causal exclusion rather than improving historical results with later information
