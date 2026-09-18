## ADDED Requirements

### Requirement: Explicit foreground paper-run lifecycle
The system SHALL provide one foreground-only paper-run entry point supporting explicit domain selection (`prediction`, `perp`, or `sports`), an explicit subset of the active crypto universe where applicable, a bounded duration or interactive interrupt, and a unique `paper_run_id`. It SHALL start in a preflight state, collect only required read-only inputs, evaluate candidates, persist decisions and simulated events, and exit cleanly on duration expiry, SIGINT, SIGTERM, a safety halt, or unrecoverable reconciliation failure. It SHALL NOT schedule, daemonize, auto-restart, or create any live order.

#### Scenario: Operator starts a bounded ETH prediction run
- **WHEN** the operator invokes the paper command for `prediction`, `ETH`, and a duration
- **THEN** the system SHALL create a distinct foreground run and stop after the requested duration

#### Scenario: Process receives SIGTERM
- **WHEN** a paper run receives SIGTERM
- **THEN** it SHALL persist the final heartbeat and open-position reconciliation status before exiting without opening another position

### Requirement: Paper-only startup guard
Before creating an authenticated client or evaluating an entry, every paper run SHALL enforce a paper-execution guard that verifies `PAPER_TRADING=true`, explicit paper mode, a safe local paper-ledger target, and absence of a mutating production order adapter. Authenticated Kalshi data access SHALL additionally require `KALSHI_USE_DEMO_ENV=true`. The guard SHALL emit a non-secret configuration fingerprint and fail closed with a clear operator-visible reason on any violation.

#### Scenario: Production environment is configured
- **WHEN** a paper command sees `KALSHI_USE_DEMO_ENV=false`
- **THEN** it SHALL refuse startup before making an authenticated Kalshi request

#### Scenario: Paper mode is disabled
- **WHEN** `PAPER_TRADING` is false
- **THEN** the command SHALL refuse startup and SHALL NOT construct a broker or client capable of placing orders

### Requirement: Registry and lifecycle admission
The orchestrator SHALL select instruments only through a registry/discovery snapshot that identifies domain, asset, lifecycle, source alignment, freshness, liquidity, and eligibility. The shipped active crypto universe SHALL be BTC, ETH, SOL, and XRP only. An asset/domain pair SHALL be admitted to `paper` only after its frozen validation and paper-admission gate pass; `disabled`, `observe`, `backtest`, and `shadow` modes SHALL record their respective behavior but SHALL NOT create simulated fills.

#### Scenario: XRP is still in shadow mode
- **WHEN** an XRP strategy produces an entry signal during a shadow run
- **THEN** the system SHALL persist the decision and block reason but SHALL NOT create a paper order or fill

#### Scenario: Unlisted configured instrument is requested
- **WHEN** discovery cannot find an active compatible ETH market within the freshness limit
- **THEN** the orchestrator SHALL mark the asset unavailable and SHALL NOT use a stale cached ticker

### Requirement: Domain adapter isolation
The orchestrator SHALL pass normalized decisions through a domain-specific paper adapter. The binary prediction adapter, perpetual adapter, and sports adapter SHALL expose a common audit envelope while retaining their own price, size, fee, position, and settlement semantics. A binary adapter SHALL NOT accept a perpetual order, and a perpetual adapter SHALL NOT write a binary `SimulatedTrade` as its source of truth.

#### Scenario: Perpetual decision reaches the execution boundary
- **WHEN** a valid perpetual decision is admitted
- **THEN** the orchestrator SHALL route it only to the perpetual paper adapter and its linear ledger

#### Scenario: Strategy returns an unknown domain
- **WHEN** a strategy emits a decision with no registered domain adapter
- **THEN** the orchestrator SHALL reject and persist the decision with `unsupported_domain`

### Requirement: Durable audit, recovery, and reconciliation
The system SHALL persist every decision—including HOLDs and blocked entries—plus source snapshots, policy/model/data-manifest hashes, risk decision, order attempt, fill/rejection, position event, funding/settlement event, heartbeat, halt, and final run summary under the paper run ID. On restart it SHALL reconstruct open paper positions from the appropriate domain ledger, fetch fresh read-only venue status/official results, and reconcile before allowing new entries. It SHALL stop new entries for orphaned, ambiguous, stale, or unresolved positions and SHALL never fabricate a settlement or quote.

#### Scenario: Restart finds a resolved binary market
- **WHEN** a restarted prediction paper run finds an open ledger position whose official Kalshi result is available
- **THEN** it SHALL settle using that result and record the reconciliation event before new entries

#### Scenario: Restart finds an ambiguous perpetual position
- **WHEN** a perpetual ledger position lacks a fresh mark or required metadata
- **THEN** the system SHALL enter reconciliation-required state and block new perpetual entries
