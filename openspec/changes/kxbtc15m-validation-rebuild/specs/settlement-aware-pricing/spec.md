## ADDED Requirements

### Requirement: Settlement-method-aware fair probability
The system SHALL estimate KXBTC15M settlement probability from the contract's published target and settlement-window methodology using timestamped BRTI observations, time remaining, and a volatility or distribution estimate. It SHALL retain the input timestamps and model version used for each estimate.

#### Scenario: Estimate before the final settlement window
- **WHEN** a KXBTC15M decision is evaluated before its final 60-second averaging window
- **THEN** the fair probability uses only BRTI observations available at that time and does not use the final settlement value

#### Scenario: Estimate during the final settlement window
- **WHEN** the decision is evaluated during the final 60-second averaging window
- **THEN** the fair probability incorporates only the observed portion of that window and projects the unobserved portion

### Requirement: Calibrated probability trade decision
The system SHALL fit probability calibration only on prior training data and SHALL compare the calibrated fair probability with side-specific executable prices and expected full trade friction before submitting a candidate trade.

#### Scenario: Directional trend lacks executable edge
- **WHEN** a trend or momentum feature points upward but calibrated YES probability does not exceed the executable YES price by the required full-cost edge
- **THEN** the system records no YES trade

#### Scenario: Calibration is assessed out of sample
- **WHEN** a validation fold completes
- **THEN** the report includes Brier score and a reliability or calibration summary calculated from that fold's outcomes

### Requirement: Conditional feature experiments
The system SHALL report trend, pullback, microprice, public-trade imbalance, and quarter-hour effects as separately identifiable features or experiments. It SHALL not treat any such feature as a promoted strategy without the causal validation and cost-aware promotion evidence required by `causal-strategy-validation`.

#### Scenario: Trend feature evaluation
- **WHEN** a candidate model includes a short-horizon trend feature
- **THEN** the experiment reports its incremental out-of-sample performance relative to the settlement-aware baseline
