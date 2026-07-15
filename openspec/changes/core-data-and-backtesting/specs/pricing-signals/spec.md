# pricing-signals

## ADDED Requirements

### Requirement: Digital option fair value via Black-Scholes
The system SHALL compute the fair value of a binary (cash-or-nothing) contract as N(d2) given spot, strike, time-to-expiry, and volatility, and SHALL support range/bucket contracts as the difference of two digital values.

#### Scenario: Known-answer digital call
- **WHEN** fair value is computed for spot=100, strike=100, vol=0.20, t=1 year, r=0
- **THEN** the result matches the analytic N(d2) value within 1e-9

#### Scenario: Deep in-the-money bound
- **WHEN** spot is far above strike with short expiry
- **THEN** fair value approaches 1.0 and never exceeds it

### Requirement: Monte Carlo cross-check with fat tails
The system SHALL provide a Monte Carlo estimate of the same contract probability using Student-t distributed shocks (fat tails), and the strategy layer MUST be able to compare Black-Scholes and Monte Carlo estimates to detect model disagreement.

#### Scenario: MC agrees with BS under normality
- **WHEN** Monte Carlo runs with high degrees-of-freedom (near-normal shocks) on a standard contract
- **THEN** its probability estimate is within statistical tolerance of the Black-Scholes value

### Requirement: Volatility estimation with fallback chain
The system SHALL estimate volatility using a priority chain (30-day historical, EWMA, intraday) where each estimator falls back to the next when insufficient data exists, and SHALL report which estimator was used.

#### Scenario: Fallback on insufficient history
- **WHEN** fewer than 30 days of history exist but intraday data is present
- **THEN** the estimator falls back down the chain and labels the estimate's source
