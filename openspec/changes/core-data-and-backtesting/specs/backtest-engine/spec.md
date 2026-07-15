# backtest-engine

## ADDED Requirements

### Requirement: Identical code path as live trading
The backtest engine SHALL invoke the same `StrategyProtocol.evaluate()` and risk-sizing functions used by live/paper modes, injecting only a different data source and `BrokerAdapter` implementation. A duplicate or vectorized re-implementation of strategy logic MUST NOT exist.

#### Scenario: Strategy object reuse
- **WHEN** a backtest is constructed
- **THEN** it accepts the same strategy instance type that the live loop will accept, unmodified

### Requirement: Pessimistic fill simulation with fees
`BacktestBroker` SHALL fill orders at the bar's worst plausible price for the order side by default and SHALL apply Kalshi's 7% fee on net winnings inside the fill/settlement model itself.

#### Scenario: Fee applied at settlement
- **WHEN** a simulated YES position settles in the money
- **THEN** recorded PnL equals gross winnings minus the 7% fee

### Requirement: Enforced out-of-sample split
`BacktestEngine.run()` SHALL require an explicit train/test date split, compute metrics per segment, and the go/no-go evaluation SHALL read only test-segment metrics.

#### Scenario: Metrics segmented
- **WHEN** a run completes with a train/test split
- **THEN** the result reports each metric separately for both segments, labeled

### Requirement: Metrics make fee-adjusted reality unmissable
The result SHALL include: achieved win rate displayed alongside the fee-adjusted breakeven win rate, Sharpe and Sortino ratios, maximum drawdown, and fee-adjusted net PnL broken out per asset and per contract cadence.

#### Scenario: Breakeven comparison present
- **WHEN** any backtest result is rendered
- **THEN** the achieved win rate and the breakeven win rate appear together in the output

### Requirement: Engine correctness is proven by known-answer replay
The test suite SHALL include synthetic price paths with hand-computed correct outcomes (which trades fire, final PnL), and the engine MUST reproduce them exactly.

#### Scenario: Synthetic replay matches hand computation
- **WHEN** the engine replays a synthetic dataset with a deterministic strategy
- **THEN** trade list and final PnL match the precomputed expected values exactly
