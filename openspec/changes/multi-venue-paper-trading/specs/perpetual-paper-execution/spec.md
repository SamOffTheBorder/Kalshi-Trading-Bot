## ADDED Requirements

### Requirement: Perpetual market discovery and paper admission
The system SHALL discover Kalshi crypto perpetual markets through authenticated read-only margin endpoints and SHALL record ticker, asset, reference index, contract multiplier, minimum order size, tick size, leverage/margin parameters, funding availability, mark/bid/ask freshness, and discovery timestamp. It SHALL consider only BTC, ETH, SOL, and XRP. A perpetual asset SHALL remain non-paper-eligible until a fresh compatible discovery snapshot, required mark/funding coverage, frozen strategy validation, paper-admission report, and bracket/liquidation drill all pass.

#### Scenario: SOL perpetual has no fresh funding metadata
- **WHEN** SOL discovery finds an active market but funding metadata is unavailable or stale
- **THEN** the system SHALL mark SOL perpetual paper admission blocked with the metadata reason

#### Scenario: Discovery returns an unconfigured crypto perp
- **WHEN** the margin API returns a valid AAVE perpetual
- **THEN** the system SHALL record the observation as non-active and SHALL NOT admit it to a paper run

### Requirement: Linear perpetual paper ledger
The system SHALL maintain a perpetual-specific paper ledger that represents signed long/short quantity, entry and exit fills, mark-to-market equity, realized and unrealized PnL, fees, funding cash flows, margin used, free collateral, leverage, liquidation estimate/distance, bracket state, and position lifecycle. It SHALL retain contract multiplier and quote currency and SHALL not reuse binary YES/NO settlement fields as perpetual accounting.

#### Scenario: Long position is marked after price movement
- **WHEN** a BTC perpetual paper position receives a fresh mark snapshot
- **THEN** the ledger SHALL update unrealized PnL, equity, leverage, and liquidation distance using the recorded multiplier

#### Scenario: Position is closed
- **WHEN** a paper perpetual position is closed by a simulated fill or risk exit
- **THEN** the ledger SHALL record the side-aware exit, realized PnL, fees, funding, and final lifecycle state

### Requirement: Conservative simulated fills and funding
The perpetual paper adapter SHALL simulate entries and exits against causal bid/ask or a documented conservative fallback, enforce tick size and minimum order size, and reject missing/stale/one-sided quotes. It SHALL use a frozen fee schedule and record the schedule version. Funding SHALL be accrued only from causal realized funding observations; an estimate may be displayed for risk information but SHALL NOT be booked as realized funding. Missing required price/funding observations SHALL result in a no-entry, reconciliation-required state, or conservative stress report rather than an invented value.

#### Scenario: Market order would cross the spread
- **WHEN** a paper strategy enters a long perpetual with fresh bid/ask data
- **THEN** the simulated fill SHALL use the ask plus any configured adverse-fill treatment and record the input quote reference

#### Scenario: Only funding estimate is available
- **WHEN** an open position reaches a funding boundary but only an estimated funding rate is present
- **THEN** the system SHALL not book it as realized funding and SHALL mark reconciliation or stress treatment required

### Requirement: Leverage, liquidation, and bracket safety
The perpetual paper adapter SHALL enforce a default maximum leverage of 2x and an absolute maximum of 3x, per-asset/domain/group/portfolio budgets, margin sufficiency, and conservative liquidation-distance policy before accepting an entry. It SHALL attach predeclared stop-loss and take-profit brackets or reject the entry if brackets cannot be represented/simulated. It SHALL simulate order/mark gaps and forced risk exits, record each event, and immediately block new entries after a liquidation, margin breach, stale critical price, or emergency halt.

#### Scenario: Requested position exceeds leverage cap
- **WHEN** a requested XRP perpetual size would produce leverage above the configured cap
- **THEN** the adapter SHALL reduce it only if the resulting size remains valid and otherwise reject it with `leverage_or_minimum_size`

#### Scenario: Bracket cannot be validated
- **WHEN** a perpetual decision lacks a valid stop-loss or take-profit representation
- **THEN** the adapter SHALL reject the paper entry before any simulated fill

### Requirement: Perpetual-specific reporting and promotion
The system SHALL report perpetual performance independently from prediction/sports results, including price PnL, funding PnL, fees, return on notional, drawdown, maximum leverage, minimum liquidation distance, liquidation count, execution quality, data coverage, and reconciliation events. Promotion from shadow to paper SHALL require a predeclared holdout and paper-admission policy that passes for the specific asset; no prediction-market success or pooled crypto metric SHALL substitute for this gate.

#### Scenario: Directional PnL masks negative funding carry
- **WHEN** a candidate's total PnL is positive but funding PnL is materially negative
- **THEN** the report SHALL show both components and SHALL NOT label the candidate funding-carry successful

#### Scenario: ETH passes prediction validation only
- **WHEN** ETH's event-contract strategy passes but its perpetual report has not passed
- **THEN** the system SHALL keep ETH perpetual in non-paper mode
