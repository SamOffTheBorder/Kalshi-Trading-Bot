## ADDED Requirements

### Requirement: Hierarchical paper-risk budgets
The system SHALL evaluate every paper entry against a versioned risk policy containing global portfolio, domain, asset, correlation-group, market/series, and daily-loss limits. BTC, ETH, SOL, and XRP SHALL share a `major-crypto` correlation group unless an explicit reviewed policy changes it. Budgets SHALL consider open paper positions, reserved entry cost/margin, realized and unrealized PnL where appropriate, worst-case binary loss, perpetual liquidation/funding stress, and pending reconciliation state. A pass at one level SHALL NOT override a failure at another level.

#### Scenario: Correlated crypto exposure is exhausted
- **WHEN** open BTC and ETH paper positions exhaust the major-crypto group budget
- **THEN** a new SOL or XRP entry SHALL be rejected even if its individual asset budget remains available

#### Scenario: Sports budget is available but global halt applies
- **WHEN** sports has unused paper budget while the global portfolio is halted
- **THEN** the sports adapter SHALL reject the entry because the global halt takes precedence

### Requirement: Freshness, integrity, and eligibility are risk controls
The system SHALL treat stale, incomplete, malformed, source-misaligned, or unverified data as a risk-admission failure. Each domain SHALL declare maximum age and required sources for quote, underlying price/mark, funding, discovery metadata, evidence, and settlement data. The risk decision SHALL persist the evaluated ages, source references, policy version, and exact blocking reason. A stale value SHALL never be refreshed implicitly from a different source or a later observation.

#### Scenario: Perpetual mark becomes stale
- **WHEN** a required Kalshi perpetual mark exceeds its policy freshness threshold
- **THEN** the risk layer SHALL block new perpetual entries and request reconciliation for affected open positions

#### Scenario: Prediction index alignment is unknown
- **WHEN** a prediction candidate has current quotes but lacks a verified settlement-index alignment
- **THEN** the risk layer SHALL block entry with `source_alignment_unknown`

### Requirement: Unified emergency halt and resumption
The system SHALL route drawdown, daily-loss, consecutive-loss, liquidation, quote/data integrity, operator request, process-signal, and reconciliation failures through one durable emergency-control state. A halt SHALL prevent new entries across every paper domain immediately and SHALL record source, reason, time, affected run/asset/domain, and policy snapshot. Resume SHALL require an explicit operator action after a fresh health/reconciliation check; a new process start SHALL not silently clear a halt.

#### Scenario: A perpetual liquidation is simulated
- **WHEN** the perpetual adapter records a liquidation or margin breach
- **THEN** emergency control SHALL halt all new paper entries and preserve the liquidation event in the audit log

#### Scenario: Operator attempts to resume prematurely
- **WHEN** an operator requests resume while a stale open position remains unreconciled
- **THEN** the control layer SHALL refuse resume and list the unresolved condition

### Requirement: Promotion and demotion are explicit
The system SHALL maintain an auditable lifecycle for every asset/domain/candidate: `disabled`, `observe`, `backtest`, `shadow`, `paper`, and `blocked`. Promotion SHALL require an operator-reviewed report with frozen data/model/risk fingerprints and all applicable per-component gates. A coverage failure, negative paper/backtest divergence, emergency halt, liquidity deterioration, source alignment failure, or data-integrity failure SHALL demote the affected scope to `blocked` or an earlier state without changing unrelated domains. This change SHALL not promote any scope to live trading.

#### Scenario: Paper behavior diverges from frozen backtest
- **WHEN** a paper report exceeds a predeclared divergence threshold for fills, costs, expectancy, or risk metrics
- **THEN** the system SHALL demote that asset/domain and block further paper entries pending review

#### Scenario: BTC prediction passes its gate
- **WHEN** BTC prediction meets all shadow and paper-admission requirements
- **THEN** the system SHALL permit only BTC prediction paper mode and SHALL leave ETH/SOL/XRP and other domains at their own lifecycle states
