## ADDED Requirements

### Requirement: Chronological per-asset validation
The system SHALL validate every BTC, ETH, SOL, and XRP underlying strategy with chronological, asset-isolated walk-forward folds. Each fold SHALL declare a training, validation, and final holdout interval; purge/embargo duration at least equal to the maximum feature lookback plus prediction horizon; data manifest; feature/model version; execution assumptions; random seed; and code/config fingerprint. The feature builder SHALL use only records available at or before each decision timestamp.

#### Scenario: Feature lookback crosses a fold boundary
- **WHEN** a target observation is within the configured purge/embargo interval after training data
- **THEN** the evaluator SHALL exclude it from validation/holdout scoring

#### Scenario: A later data revision exists
- **WHEN** an artifact revision was retrieved after the frozen manifest was created
- **THEN** the evaluator SHALL not use that revision in the run

### Requirement: Instrument-aware prediction-market validation
The system SHALL evaluate a prediction-market candidate in two distinct layers: underlying-signal quality and Kalshi binary-contract execution/outcome quality. The contract layer SHALL use the actual contract rules, close/settlement window, decision-time Kalshi quote, side-aware fees, observable liquidity, and official resolution. Before a candidate can be paper-admitted, the system SHALL produce a `source_alignment` verdict between external underlying data, any BRTI/index data, and the contract's documented settlement source. An unknown or incompatible verdict SHALL block paper admission.

#### Scenario: External BTC price differs from a contract settlement index
- **WHEN** a Kalshi contract resolves from a documented index not proven equivalent to the external spot source
- **THEN** the system SHALL retain the external feature result but mark contract paper admission blocked for source misalignment

#### Scenario: Contract quote is unavailable at decision time
- **WHEN** no causal two-sided Kalshi quote is available for a proposed entry
- **THEN** the system SHALL record a no-trade rather than simulate a fill at a later quote

### Requirement: Realistic domain-specific backtest economics
The system SHALL apply execution economics appropriate to the instrument. Binary-event tests SHALL use side-aware contract prices, documented event fees, observable spread and liquidity constraints, and official settlement. Perpetual tests SHALL separately model bid/ask execution, multiplier, minimum order size, fees, funding, margin, leverage, mark-to-market, and liquidation distance. A model report SHALL not combine binary and perpetual PnL into one strategy metric.

#### Scenario: A perpetual strategy earns price PnL but pays funding
- **WHEN** a simulated perp position crosses a funding timestamp
- **THEN** the backtest SHALL include the signed funding payment in the perpetual ledger and metrics

#### Scenario: Binary and perpetual candidates are compared
- **WHEN** an operator opens an aggregate report
- **THEN** the report SHALL show domain-separated returns and SHALL NOT sum them into an approval metric

### Requirement: Baselines, metrics, and component-level gates
The system SHALL compare every candidate with predeclared baselines, including a no-trade after-cost result and an appropriate market/naïve signal benchmark. Reports SHALL include coverage, sample count, data gaps, trade/decision count, calibration and Brier score when probabilities exist, realized/modelled costs, fills/rejections, expectancy, drawdown, confidence interval, and domain-specific risk metrics. Promotion SHALL require every asset/cadence/domain component in scope to pass its own minimum sample, coverage, economics, and risk thresholds; a pooled aggregate SHALL NOT override a failed component.

#### Scenario: Aggregate result is positive but SOL fails
- **WHEN** BTC, ETH, and XRP pass but SOL's holdout expectancy or coverage gate fails
- **THEN** the system SHALL mark SOL blocked and SHALL NOT promote it because of the aggregate result

#### Scenario: A model has no executable post-cost edge
- **WHEN** a model exceeds its pre-cost benchmark but fails the no-trade-after-cost comparison
- **THEN** the report SHALL classify it as non-promotable

### Requirement: Training and LLM boundaries
The system SHALL use only frozen structured observations and captured, timestamped, allowlisted evidence records as model inputs. LLM output SHALL be advisory metadata only: it may summarize a captured record but SHALL NOT label an outcome, generate an untracked training feature, choose a model threshold after holdout evaluation, or place/authorize an order. Every candidate SHALL identify whether any evidence-derived feature was present and its evidence/version hashes.

#### Scenario: LLM response lacks captured citations
- **WHEN** an LLM-generated sports or market summary has no eligible evidence references
- **THEN** the system SHALL exclude it from training and paper-admission inputs

#### Scenario: Operator requests a post-holdout threshold change
- **WHEN** a threshold is altered after viewing final holdout results
- **THEN** the system SHALL require a new frozen configuration and a new untouched holdout before a promotion verdict
