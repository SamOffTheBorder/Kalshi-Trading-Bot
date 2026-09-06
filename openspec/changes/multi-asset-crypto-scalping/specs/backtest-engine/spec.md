## ADDED Requirements

### Requirement: Multi-asset backtests run on the causal validation path
Every per-asset and per-cadence backtest SHALL execute on the
`causal-strategy-validation` simulation path: decisions consume only
observations whose availability timestamp is at or before the decision
timestamp, an incomplete bar's future high/low/close/volume SHALL NOT influence
a decision or a fill, and each fold SHALL use a newly initialized broker, cash
balance, and risk guards. Side-aware YES/NO lifecycle and both-leg fee
accounting SHALL apply identically for every asset. Extending the engine to a
new asset SHALL NOT introduce an asset-specific execution path that bypasses
these rules.

#### Scenario: New asset reuses the causal simulator
- **WHEN** ETH or another registry asset is added to a multi-asset backtest
- **THEN** its trades and fills obey the same as-of timeline, incomplete-bar exclusion, per-fold state isolation, and side-aware fee accounting as KXBTC15M

#### Scenario: Incomplete bar cannot fill a per-asset order
- **WHEN** a decision for any asset occurs during an OHLC bar
- **THEN** the simulator excludes that bar's future high, low, close, and volume and does not use it to fill the order

### Requirement: Registered-underlying and cadence context assembly
The backtest engine SHALL resolve each event market's underlying through the
asset registry, identify whether it is a 15-minute or hourly market, and
assemble its `StrategyContext` using only that asset's spot and market history.
A market without a valid mapping SHALL be skipped with a recorded reason.

#### Scenario: ETH event market is evaluated
- **WHEN** a valid ETH prediction-market candle is evaluated in a backtest
- **THEN** the context SHALL use ETH spot bars and volatility and SHALL identify ETH in its recorded inputs

#### Scenario: ETH hourly market is evaluated
- **WHEN** a valid ETH hourly strike-ladder candle is evaluated in a backtest
- **THEN** the context SHALL use ETH spot history, identify the hourly cadence, and apply the declared hourly contract-shape rules

### Requirement: Per-asset and aggregate results
Each multi-asset backtest SHALL persist an immutable registry/configuration
snapshot and produce train/test metrics by asset and cadence in addition to
aggregate portfolio metrics. Aggregate metrics SHALL NOT mark an asset or
cadence as passing.

#### Scenario: One asset loses while portfolio aggregate wins
- **WHEN** aggregate test metrics pass a configured threshold but an asset's own frozen test metrics fail
- **THEN** that asset SHALL remain ineligible for promotion and the report SHALL show the conflicting results

### Requirement: Comparable evaluation scope
The engine SHALL record the selected assets, per-asset data windows, gaps,
evaluation stride, and liquidity filters with a run so an operator can
distinguish a genuine asset comparison from differences in available history.

#### Scenario: Assets have different data coverage
- **WHEN** a multi-asset backtest contains assets with unequal eligible windows
- **THEN** the result SHALL report each asset's window and SHALL not present the aggregate as a like-for-like comparison without that disclosure
