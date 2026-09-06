# backtest-engine

## MODIFIED Requirements

### Requirement: Pessimistic fill simulation with fees
`BacktestBroker` SHALL fill orders at the bar's worst plausible price for the order side by default and SHALL apply Kalshi's actual fee schedule: a per-contract fee of `ceil(coefficient × P × (1 − P) × contracts × 100) / 100` dollars charged **at entry regardless of outcome**, with coefficient `0.07` for taker fills and `0.0175` for maker fills. No fee SHALL be charged at settlement.

#### Scenario: Fee charged at entry on a losing trade
- **WHEN** a simulated position is entered and later settles worthless
- **THEN** the recorded cost includes the entry fee, and no settlement fee is applied

#### Scenario: Maker fill costs a quarter of taker
- **WHEN** the same order is simulated as a resting fill and as a crossing fill
- **THEN** the maker fee is one quarter of the taker fee for that price and size

### Requirement: Metrics make fee-adjusted reality unmissable
The result SHALL include achieved win rate displayed alongside the fee-adjusted breakeven win rate, Sharpe and Sortino ratios, maximum drawdown, and fee-adjusted net PnL. It SHALL additionally report **trade concentration** (share of net profit contributed by the ten largest winners), the R-multiple distribution, maximum consecutive losses, and results recomputed under flat position sizing.

#### Scenario: Concentration surfaced
- **WHEN** a backtest completes
- **THEN** the share of profit attributable to the top ten trades is reported

#### Scenario: Flat-sizing counterfactual reported
- **WHEN** a backtest completes using variable sizing
- **THEN** the equivalent result under flat sizing is reported alongside it

## ADDED Requirements

### Requirement: Entry gates are evaluated against the actual fill
Strategy entry conditions that depend on price SHALL be validated against the executed fill price. A fill that falls outside the strategy's stated entry band SHALL be rejected rather than recorded as a position.

#### Scenario: Fill outside entry band rejected
- **WHEN** the simulated fill price implies a win probability outside the strategy's configured entry band
- **THEN** no position is opened and the rejection is recorded

### Requirement: Only live markets are tradeable
The engine SHALL reject entries in markets lacking a two-sided quote or lacking non-zero open interest at the evaluation timestamp.

#### Scenario: Phantom strike excluded
- **WHEN** a market shows a zero bid or zero open interest
- **THEN** no entry is generated for it

### Requirement: Holdout integrity
The out-of-sample segment SHALL be designated before tuning and SHALL be evaluated only when a configuration is declared final. The number of times a configuration has been evaluated against the holdout SHALL be recorded with the run.

#### Scenario: Holdout evaluation counted
- **WHEN** a run evaluates the holdout segment
- **THEN** the run record includes the holdout evaluation count for that configuration
