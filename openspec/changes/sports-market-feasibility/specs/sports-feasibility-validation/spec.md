## ADDED Requirements

### Requirement: Candidate probabilities are evaluated against the market baseline
The feasibility evaluator SHALL compare each candidate probability with the
contemporaneous Kalshi implied probability in predeclared time-to-event
buckets. It SHALL report calibration and probabilistic accuracy for the
candidate and market baseline separately.

#### Scenario: Candidate is more accurate but not calibrated
- **WHEN** a candidate has higher directional accuracy than the market but
  worse calibration or probabilistic score on the holdout
- **THEN** the report identifies that outcome and SHALL NOT call the candidate
  validated on accuracy alone

### Requirement: Validation uses point-in-time inputs and a frozen holdout
The evaluator SHALL use only observations available at the decision time and
shall fit feature transforms, calibration, and thresholds using training data
that precedes a pre-registered chronological holdout.

#### Scenario: Holdout data is encountered during fitting
- **WHEN** a calibration or threshold-fitting operation would consume a
  holdout observation
- **THEN** the operation is rejected and the run is marked invalid

### Requirement: Simulated entries are execution-realistic
The evaluator SHALL simulate an entry only at an actual eligible quote or a
configured resting limit-fill condition. It SHALL apply the market-specific
fee schedule, bid-ask spread, configured slippage, available depth, and
partial-fill or rejection behavior before recording net PnL.

#### Scenario: Edge disappears after realistic friction
- **WHEN** a candidate's gross edge is positive but does not clear fees,
  spread, slippage, and available-depth constraints at the simulated fill
- **THEN** no simulated position is opened and the rejection is recorded

### Requirement: Feasibility reports make insufficiency and concentration explicit
Every report SHALL include sample count, opportunity count, eligible and
rejected fills, fee-adjusted net PnL, calibration metrics, market-baseline
comparison, time-to-event segmentation, trade concentration, maximum
drawdown, and an explicit `research_promising`, `park`, or `insufficient_data`
outcome.

#### Scenario: Small sample is not promoted
- **WHEN** a candidate has not met its predeclared minimum sample size or
  confidence threshold
- **THEN** the outcome is `insufficient_data` regardless of positive gross or
  net PnL

### Requirement: Sports feasibility does not authorize execution
The result of this evaluator SHALL NOT enable paper or live sports orders.

#### Scenario: Candidate clears research gate
- **WHEN** a candidate receives a `research_promising` outcome
- **THEN** the system records that a separate paper-trading change is required
  before any sports order path can be enabled
