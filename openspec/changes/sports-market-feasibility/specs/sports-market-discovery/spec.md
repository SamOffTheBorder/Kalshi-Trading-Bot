## ADDED Requirements

### Requirement: Sports series and market eligibility is discovered explicitly
The system SHALL enumerate Kalshi sports series and their candidate markets
through public API data and persist one discovery result per evaluated market.
Each result SHALL include the series and market identifiers, category or sport,
contract title, close time, outcome shape, settlement-source metadata, fee
metadata when available, observed liquidity fields, eligibility status, and a
specific failure reason when ineligible.

#### Scenario: Eligible two-outcome game market recorded
- **WHEN** a discovered market has a known settlement source, exactly two
  mutually exclusive outcomes, a two-sided quote, non-zero open interest, and
  configured liquidity thresholds
- **THEN** it is persisted as eligible with the observed screening inputs

#### Scenario: Unsupported contract shape rejected
- **WHEN** a discovered market is an outright future, player prop, combo,
  multi-outcome event, or otherwise cannot be classified as a two-outcome
  single-game market
- **THEN** it is persisted as ineligible with the applicable failure reason

### Requirement: Eligibility is based on current observable liquidity
The discovery process SHALL evaluate bid, ask, spread, available top-of-book
size or depth when available, open interest, and volume at the discovery time.
It SHALL NOT infer tradability from a series title or aggregate historical
volume alone.

#### Scenario: High-volume but one-sided market rejected
- **WHEN** a market reports historical volume but lacks a current two-sided
  quote or configured minimum depth
- **THEN** the market is ineligible for capture and simulation at that time

### Requirement: Market rules are auditable
The discovery record SHALL retain a snapshot or content-addressed reference to
the market's rule and settlement-source metadata used to classify it.

#### Scenario: Rules changed after discovery
- **WHEN** a later discovery observes changed rule or settlement metadata for
  the same market identity
- **THEN** the later record is distinguishable from the earlier record and a
  validation run can identify which version it used
