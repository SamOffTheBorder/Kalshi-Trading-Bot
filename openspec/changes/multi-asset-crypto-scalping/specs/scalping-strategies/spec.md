## ADDED Requirements

### Requirement: Per-asset and per-cadence strategy eligibility
An asset SHALL not advance from observation to paper or live strategy use until
each selected cadence has its own frozen out-of-sample evidence and configured
market-quality criteria pass. That evidence SHALL meet the
`causal-strategy-validation` cost-aware promotion bar and, for a settlement
market, SHALL be produced by a calibrated `settlement-aware-pricing`
probability model; short-horizon trend, pullback, microprice, order-flow
imbalance, and quarter-hour effects count only as conditional features that
improve out-of-sample net value after execution costs, never as standalone
promoted edges. Strategy decisions MUST retain the asset, cadence, and
asset/cadence-specific hold reason in the audit trail.

#### Scenario: Bare trend signal proposed for a new asset
- **WHEN** an ETH cadence's only supporting evidence is a positive short-horizon trend feature without a calibrated settlement-aware probability that beats the executable price by the full-cost edge
- **THEN** that ETH cadence SHALL NOT be admitted to paper or live execution

#### Scenario: ETH is first expansion candidate
- **WHEN** ETH has sufficient valid data but its 15-minute or hourly test gate has not cleared
- **THEN** that ETH cadence MAY be backtested but SHALL not be admitted to paper or live execution

### Requirement: No pooled parameter promotion
The system SHALL not use performance pooled across BTC and other assets as the
sole basis to tune or approve a strategy configuration for an individual asset.

#### Scenario: Pooled data produces a favorable parameter
- **WHEN** a configuration performs well in aggregate but an asset-specific test segment does not pass
- **THEN** the configuration SHALL not authorize that asset and the report SHALL preserve the asset-specific failure
