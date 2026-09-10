## ADDED Requirements

### Requirement: Flow features are anonymous and causal
The system SHALL derive flow features only from captured Kalshi trades,
quotes, and order books available at the simulated decision time. It SHALL
not infer, store, or expose a trader identity.

#### Scenario: Public trade has no identity
- **WHEN** a public trade is ingested
- **THEN** the feature row uses ticker, side, price, size, and timestamps only
  and records identity as unavailable

### Requirement: Flow candidates are benchmarked against the market
The evaluator SHALL test signed imbalance, notional flow, book imbalance,
quote replenishment, spread/depth changes, and post-flow response against the
contemporaneous market baseline with fees and executable depth applied.

#### Scenario: Flow edge disappears after costs
- **WHEN** a flow candidate has positive gross edge but fails the existing
  fee, spread, slippage, or depth constraints
- **THEN** the candidate is rejected and the reason is included in the report

### Requirement: Named-trader copying is unsupported by default
The system SHALL label identity-based copy trading unsupported unless a
separately approved venue and adapter provide lawful attributable public
positions.

#### Scenario: Operator requests Kalshi trader copying
- **WHEN** no attributable public identity field exists
- **THEN** the system refuses the copy strategy and offers anonymous-flow
  research instead
