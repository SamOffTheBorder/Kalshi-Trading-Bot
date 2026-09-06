## ADDED Requirements

### Requirement: Asset-specific perpetual validation
Before a non-BTC perpetual is eligible for paper or live use, the system SHALL
validate its active margin market, contract multiplier/minimum size, leverage
limit, funding data, and reference-index metadata through the authenticated
margin API. Missing or stale validation SHALL block new entries. Metadata
validation is necessary but not sufficient: a non-BTC perpetual strategy SHALL
be promoted only through the independent perpetual gate defined in
`perps-strategy-isolation`, never on the strength of an event-contract
strategy's results.

#### Scenario: Perp metadata changes
- **WHEN** the margin API reports a contract size or maximum leverage different from the stored asset metadata
- **THEN** the system SHALL refresh the persisted discovery result and SHALL use neither stale sizing nor a trade until validation succeeds

#### Scenario: Event strategy passes but the asset's perp strategy has no evidence
- **WHEN** an asset's binary-event strategy clears its paper-trading gate and the same asset's perpetual strategy has not passed the `perps-strategy-isolation` gate
- **THEN** the perpetual for that asset SHALL remain disabled

### Requirement: Compatible event-perp hedges only
The system SHALL NOT classify a funding-carry or other cross-instrument position
as market neutral when one leg is a discontinuous binary event contract hedging
a linear perpetual exposure. Registry verification of the same asset and a
compatible settlement/reference index for both legs is necessary but not
sufficient; a funding-carry candidate SHALL additionally demonstrate a
compatible linear hedge, its rebalance cadence, complete fees, and residual
basis risk and pass the `perps-strategy-isolation` gate before it is enabled.

#### Scenario: Binary hedge proposed for linear perpetual exposure
- **WHEN** a funding-carry configuration pairs a linear perpetual position with binary event contracts as its only hedge
- **THEN** the system SHALL reject the market-neutral classification and SHALL NOT enable the configuration even when the registry confirms the asset and reference index match

#### Scenario: Prediction-only asset signals funding carry
- **WHEN** BNB, NEAR, ZEC, or another asset has no validated compatible perpetual
- **THEN** the funding-carry strategy SHALL return HOLD with a compatibility reason and SHALL not create an unhedged perp order

### Requirement: Perpetual protection is unchanged across assets
Every validated non-BTC perpetual entry SHALL obey the existing hard leverage
ceiling and SHALL attach server-side stop-loss protection; failure to attach it
MUST trigger the existing immediate-close behavior.

#### Scenario: ETH bracket attachment fails
- **WHEN** an ETH perpetual entry fills and its stop-loss attachment fails
- **THEN** the system SHALL immediately close the ETH position and record the failure

