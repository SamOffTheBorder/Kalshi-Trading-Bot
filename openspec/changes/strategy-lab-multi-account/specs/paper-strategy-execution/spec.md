# Paper strategy execution

## ADDED Requirements

### Requirement: Named strategy registry

The system SHALL provide a registry mapping a `strategy_id` to a constructed
strategy instance and its frozen configuration. A run started with a given
`strategy_id` SHALL evaluate that strategy, and the `strategy_id` recorded in
the audit trail SHALL be the identifier that selected the behaviour.

An unknown `strategy_id` SHALL be refused at preflight with reason
`unknown_strategy_id`, before any market data is fetched or any run row is
written.

#### Scenario: A registered strategy is selected by id
- **WHEN** a run is started with `--strategy trend_scalp`
- **THEN** the run evaluates `TrendScalpStrategy` with its registered config
- **AND** the persisted `PaperRun.config_fingerprint` records the registered
  config version

#### Scenario: An unknown strategy id is refused before the run starts
- **WHEN** a run is started with `--strategy does_not_exist`
- **THEN** preflight fails with reason `unknown_strategy_id`
- **AND** no `PaperRun` row is written

#### Scenario: The default is a strategy that never enters
- **WHEN** a run is started with no `--strategy` argument
- **THEN** the run uses the hold strategy and records decisions without fills

### Requirement: Gate status is carried onto every run

Every registry entry SHALL declare a gate status of `passed`, `gate_failed`,
`never_gated`, or `parked`. The status SHALL be persisted on the run and
surfaced in operator views.

A strategy whose gate status is not `passed` SHALL NOT have that status
altered by any paper-trading result. Paper evidence is an input to a future
gate decision, never a substitute for one.

#### Scenario: A gate-failed strategy is runnable but labelled
- **WHEN** a paper run is started with `trend_scalp`, whose recorded status is
  `gate_failed`
- **THEN** the run proceeds
- **AND** the run and its dashboard row are labelled `gate_failed`

#### Scenario: A profitable paper run does not upgrade gate status
- **WHEN** a `gate_failed` strategy finishes a paper run with positive PnL
- **THEN** its registry gate status remains `gate_failed`

### Requirement: Strategy context assembly is causal

The adapter SHALL assemble a `StrategyContext` for each evaluation using only
observations whose `available_at` is at or before `now_ts`. No field SHALL be
populated from a value the operator could not have observed at `now_ts`.

Where a required input is unavailable, the context field SHALL be left unset
and the strategy SHALL decide, rather than the adapter substituting a
forward-filled or default value.

#### Scenario: A later observation is excluded from context
- **GIVEN** a spot bar whose `available_at` is after `now_ts`
- **WHEN** the context is assembled for `now_ts`
- **THEN** that bar is absent from `spot_bars`

#### Scenario: Missing trend history yields an unset field, not a default
- **GIVEN** insufficient history to compute a trend z-score
- **WHEN** the context is assembled
- **THEN** `trend_zscore` is `None` and no trend gate is applied

### Requirement: Concurrent paper accounts are isolated

The system SHALL support multiple concurrent paper runs, each with its own
strategy, configuration, asset set, and bankroll. Each run's positions, fills,
audit events, and capital SHALL be attributable to exactly one `paper_run_id`.

Sizing for one run SHALL NOT observe the capital, positions, or equity of any
other run.

#### Scenario: Two runs with different strategies do not interact
- **WHEN** two paper runs are started concurrently with different strategies
- **THEN** each run's fills are recorded against its own `paper_run_id`
- **AND** neither run's sizing observes the other's cash or open positions

#### Scenario: One run halting does not halt another
- **GIVEN** two concurrent runs
- **WHEN** one run's drawdown guard halts it
- **THEN** the other run continues to evaluate and record

### Requirement: The reconstructed-data boundary survives strategy selection

The system SHALL refuse fills for a run whose frozen admission report is
backed by a `reconstructed` manifest, with reason
`reconstructed_data_not_admissible`, regardless of which strategy is
selected. Decision recording SHALL continue.

#### Scenario: A strategy signalling entry on reconstructed data records but does not fill
- **GIVEN** a run backed by a `reconstructed` manifest
- **WHEN** the selected strategy emits a BUY decision
- **THEN** the decision is recorded
- **AND** no fill is created, with reason `reconstructed_data_not_admissible`
