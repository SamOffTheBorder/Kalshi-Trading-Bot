# fixed-risk-sizing

## ADDED Requirements

### Requirement: Flat fractional risk replaces Kelly on the live path
Live position size SHALL be computed as `(equity × risk_fraction) / R`, where `risk_fraction` defaults to 0.01 and is capped at 0.02. Kelly sizing SHALL NOT size live orders.

#### Scenario: Size scales with stop distance
- **WHEN** two entries have the same equity and risk fraction but different stop distances
- **THEN** the entry with the wider stop receives proportionally fewer contracts

#### Scenario: Risk fraction cap enforced
- **WHEN** a configured risk fraction exceeds the cap
- **THEN** configuration validation fails

### Requirement: Position size bounded by observed liquidity
Order size SHALL be capped at a configurable fraction of recently observed traded volume for that market.

#### Scenario: Illiquid market caps size
- **WHEN** the computed size exceeds the liquidity cap for the market
- **THEN** the order is reduced to the cap or rejected if the cap rounds to zero

### Requirement: Daily loss limit halts trading
The system SHALL halt new entries when either a daily loss threshold or a consecutive-loss count is reached, requiring explicit human resume.

#### Scenario: Consecutive losses halt entries
- **WHEN** the configured number of consecutive losing trades occurs
- **THEN** new entries are blocked and the halt reason is recorded and surfaced
