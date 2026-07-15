# crypto-mispricing-strategy

## ADDED Requirements

### Requirement: Strategy implements the shared protocol
`CryptoMispricingStrategy` SHALL implement `StrategyProtocol` — `evaluate(context: StrategyContext) -> Decision` — with no imports from any broker adapter, data client, or execution module. The identical class MUST be usable by the backtest engine and (in later changes) paper/live loops without modification.

#### Scenario: Broker-agnostic evaluation
- **WHEN** `evaluate()` is called with a fully-populated `StrategyContext`
- **THEN** it returns a `Decision` (BUY_YES / BUY_NO / HOLD with edge and confidence) using only the context contents

### Requirement: Edge is fee-adjusted before any gate
The strategy SHALL subtract Kalshi's fee (7% of net winnings) from the computed edge before comparing against the minimum-edge threshold. Raw (pre-fee) edge MUST NOT be used in any entry decision.

#### Scenario: Fee turns marginal edge negative
- **WHEN** a contract's raw edge is positive but smaller than the fee impact
- **THEN** the decision is HOLD

### Requirement: Model-disagreement guard
The strategy SHALL return HOLD when Black-Scholes and Monte Carlo probability estimates disagree by more than a configured threshold, regardless of apparent edge.

#### Scenario: Divergent models block entry
- **WHEN** BS and MC estimates differ by more than the configured maximum divergence
- **THEN** the decision is HOLD and the reason is recorded

### Requirement: Every evaluation is persisted
The system SHALL persist every `Decision` (including HOLDs) with its inputs and reasoning to the schema of record, forming a complete audit trail — not only executed trades.

#### Scenario: HOLD decisions are auditable
- **WHEN** an evaluation results in HOLD
- **THEN** a signal row is stored with the computed edge, model values, and hold reason
