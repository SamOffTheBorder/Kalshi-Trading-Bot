## ADDED Requirements

### Requirement: Instrument-scoped causal simulation
The system SHALL run baseline validation only on an explicitly selected instrument and SHALL label every result with that instrument and dataset provenance. A decision SHALL consume only observations whose availability timestamp is at or before the decision timestamp, and an order SHALL not fill until a later eligible market-data event.

#### Scenario: KXBTC15M baseline excludes other series
- **WHEN** the baseline validation run is requested for KXBTC15M
- **THEN** its trades, metrics, and promotion evidence contain no observations or fills from another series

#### Scenario: Incomplete bar cannot influence a decision or fill
- **WHEN** a decision occurs during an OHLC bar
- **THEN** the simulator excludes that bar's future high, low, close, and volume and does not use it to fill the order

### Requirement: Side-aware lifecycle and cost accounting
The system SHALL record the held YES or NO side, each entry and exit fill price and quantity, and every matched-order fee. It SHALL calculate NO-side early-close proceeds using the NO exit value and SHALL charge a close-leg fee for an early exit.

#### Scenario: NO position gains when NO exit price rises
- **WHEN** a simulated NO position is closed at a higher NO price than its entry price after fees
- **THEN** the realized PnL reflects the increase in NO value and both entry and exit transaction fees

#### Scenario: Resting order has no fill evidence
- **WHEN** a simulated maker order lacks a validated queue/partial-fill model and no observed fill is present
- **THEN** the simulator records the order as unfilled rather than inferring a fill from a candle range

### Requirement: Isolated out-of-sample evaluation
The system SHALL evaluate each out-of-sample fold with a newly initialized broker, cash balance, and risk guards. Feature history may be seeded from observations before the fold, but simulated positions, guard state, and realized cashflow SHALL not cross the fold boundary.

#### Scenario: Training halt does not halt the test fold
- **WHEN** a drawdown or daily loss guard halts simulated trading in a training fold
- **THEN** the independently initialized test fold remains eligible to evaluate its own trades

### Requirement: Cost-aware promotion evidence
The system SHALL publish per-fold and aggregate net expectancy after modeled execution costs, trade coverage, Brier score and calibration information for probability strategies, fill/cancel/partial-fill rates, adverse-selection metrics, and day-blocked uncertainty estimates. A strategy SHALL not be promoted based on legacy v2 backtest metrics.

#### Scenario: Candidate fails uncertainty gate
- **WHEN** a candidate's day-blocked uncertainty interval does not support positive net expectancy after costs
- **THEN** the report marks the candidate as not eligible for promotion

#### Scenario: Breakeven is specific to the trade configuration
- **WHEN** a report presents a breakeven win rate
- **THEN** it derives the rate from that trade's executable entry, stop, target, and both-leg costs rather than a fixed global threshold
