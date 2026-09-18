# perps-trading

## ADDED Requirements

### Requirement: No unbracketed leveraged position
A perpetual-futures position SHALL NOT exist without server-side stop-loss protection. If bracket attachment fails after entry, the system SHALL close the position immediately.

#### Scenario: Bracket attachment fails
- **WHEN** a perps entry fills but the exit-trigger call returns an error
- **THEN** the system submits a closing order for that position and records the incident

#### Scenario: Bot process dies with position open
- **WHEN** the trading process is killed while a bracketed perps position is open
- **THEN** the stop-loss remains active server-side and is honored by the exchange without the bot running

### Requirement: Leverage ceiling below exchange maximum
Effective leverage SHALL be capped at 2x by default with a hard ceiling of 3x, regardless of the higher maximum the exchange permits.

#### Scenario: Excess leverage rejected
- **WHEN** a position size would imply effective leverage above the configured ceiling
- **THEN** the order is rejected or reduced to satisfy the ceiling

### Requirement: Liquidation buffer enforcement
The system SHALL refuse entries whose stop-loss price sits at or beyond the position's liquidation price, so the stop is always reached before liquidation.

#### Scenario: Stop inside liquidation zone
- **WHEN** the computed stop distance exceeds the distance to liquidation
- **THEN** the entry is rejected with a recorded reason

### Requirement: Funding-rate awareness
The system SHALL track the next funding timestamp, the current funding-rate estimate, and whether an open position pays or receives funding.

#### Scenario: Funding state available
- **WHEN** a perps position is open
- **THEN** the next funding time and the estimated payment direction and magnitude are retrievable and displayed
