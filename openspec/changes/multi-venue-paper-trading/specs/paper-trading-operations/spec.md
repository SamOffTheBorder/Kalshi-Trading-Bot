## ADDED Requirements

### Requirement: Domain-first website visibility
The website SHALL provide first-class Prediction Markets, Perpetuals, and Sports areas plus an all-domain overview. Each view SHALL show the active BTC/ETH/SOL/XRP universe where relevant, lifecycle state, data coverage/freshness, source/manifest provenance, discovery and alignment status, strategy/candidate version, validation and paper metrics, risk budget/control state, open/reconciled paper positions, and exact entry blockers. Sports SHALL visibly display research-only/disabled status until its gate passes. An unavailable, stale, or unverified input SHALL not render as eligible.

#### Scenario: SOL has no active prediction series
- **WHEN** the dashboard receives a stale or missing SOL discovery snapshot
- **THEN** it SHALL show SOL as unavailable with the snapshot reason and SHALL NOT show it as paper-ready

#### Scenario: Sports feasibility is incomplete
- **WHEN** the first combined sports report has not passed
- **THEN** the Sports area SHALL state that paper execution is disabled and identify the missing evidence/report condition

### Requirement: Auditable operator commands
The system SHALL provide documented foreground commands for source discovery, external artifact import/validation, manifest creation, strategy backtest, shadow run, paper run, health/report generation, reconciliation, halt, and resume. Commands that select data, domain, assets, a strategy, or a risk policy SHALL require explicit arguments or display their safe defaults. A command SHALL write an audit event with its non-secret effective configuration, selected manifest/snapshot IDs, operator timestamp, outcome, and failure reason. No command in this change SHALL create a scheduler, service, or live order.

#### Scenario: Operator starts a paper run without a manifest
- **WHEN** the selected asset/domain requires underlying validation but no approved manifest/report is supplied
- **THEN** the command SHALL refuse startup and print the exact required evidence IDs

#### Scenario: Operator imports data with an invalid mapping
- **WHEN** a supplied symbol/cadence/quote-currency mapping conflicts with the registry
- **THEN** the importer SHALL reject the artifact and write an auditable mapping failure

### Requirement: Paper-run health and reconciliation reports
The system SHALL generate a run-health report for every paper run and on demand. It SHALL include heartbeat age, process lifecycle, data-source and quote/mark/evidence freshness, raw-data gaps, current halt state, rejected decisions by reason, positions and ledger balances, margin/liquidation details for perps, pending settlements, reconciliation state, model/data/risk fingerprints, and divergence from the frozen backtest assumptions. A report SHALL clearly distinguish no trades because of no signal from no trades because of a block/failure.

#### Scenario: No decisions are executed due to stale data
- **WHEN** a run has no fills because every candidate had stale required data
- **THEN** the health report SHALL attribute the outcome to freshness blocks rather than zero strategy signals

#### Scenario: Ledger cash does not reconcile
- **WHEN** recorded paper events do not reconcile to the computed event/perp ledger balance
- **THEN** the report SHALL mark the run unhealthy and the orchestrator SHALL block new entries until reconciliation

### Requirement: Domain-separated reporting and export
The system SHALL produce exportable reports for prediction, perpetual, and sports paper runs separately, with an optional overview that does not combine incompatible PnL or approval metrics. Reports SHALL include the precise data/evidence manifests, configuration/model/risk versions, cost/fill assumptions versus observed paper results, settlement/funding events, and promotion verdict. Exports SHALL omit secret values and retain source attribution required by provider terms.

#### Scenario: Operator requests a combined paper report
- **WHEN** the report includes prediction and perpetual activity
- **THEN** it SHALL show separate ledgers and promotion verdicts, with any portfolio overview clearly labelled non-promotional

#### Scenario: Report is shared outside the machine
- **WHEN** an operator exports a report
- **THEN** the export SHALL exclude API keys, private-key paths, tokens, and other secret configuration values

### Requirement: Website controls remain paper-safe
The website SHALL be read-only by default. If a local authenticated operator control is implemented for halt/resume or launching a foreground helper, it SHALL require a paper-only confirmation, use the same emergency-control/audit path as the command line, expose no live-trading control, and fail closed when dashboard authentication is absent. The command line remains the canonical execution entry point for this change.

#### Scenario: Unauthenticated user opens a control route
- **WHEN** dashboard authentication is absent or invalid
- **THEN** the website SHALL not expose or execute a halt, resume, or run-control action

#### Scenario: Authenticated operator requests a halt
- **WHEN** a local authenticated operator requests a paper halt from the website
- **THEN** the system SHALL persist the same emergency-control event used by the command line and stop new entries in all domains
