## ADDED Requirements

### Requirement: Versioned ranked candidate catalog

The research portfolio SHALL assign every candidate a stable ID, revision, domain,
rank, disposition (`priority`, `incubator`, `benchmark`, or `reject`), supported
asset/instrument/cadence scope, economic mechanism, entry and exit hypothesis,
required data, comparison benchmark, falsification rule, and promotion gate.
Ranks SHALL express research order and SHALL NOT represent expected returns or
evidence that an edge exists. Contract availability SHALL be resolved through the
asset registry and verified instrument metadata rather than guessed tickers.

#### Scenario: Candidate has no verified listing
- **WHEN** a catalog candidate references an asset or cadence with no verified compatible instrument
- **THEN** its research card records the missing listing as a prerequisite and does not present the instrument as tradable

#### Scenario: Research ranking is displayed
- **WHEN** an operator views the portfolio
- **THEN** each candidate shows its rank, disposition, hypothesis, required evidence, and reason for its current state

### Requirement: Initial perpetual candidate coverage

The initial perpetual portfolio SHALL include reference-basis dislocation and
convergence, short-horizon momentum/pullback, and level-break continuation as
priority experiments. Basis tests SHALL compare executable perpetual prices with
a validated reference, retain the possibility of persistent divergence, and
separate funding from price PnL. Momentum and continuation tests SHALL specify
their horizon, volatility regime, invalidation condition, and complete round-trip
costs before evaluation. Quarter-hour/session-boundary effects SHALL be tested as
incremental features. Cross-asset relative strength SHALL remain an incubator
until synchronized multi-leg data and leg-risk simulation qualify. Funding SHALL
be available as a regime and cost feature; market-neutral funding carry SHALL
remain blocked until compatible linear hedging and rebalance economics qualify.

#### Scenario: Positive funding is the only carry evidence
- **WHEN** a proposed carry experiment has positive quoted funding but lacks a compatible linear hedge or rebalance-cost evidence
- **THEN** the catalog reports the missing prerequisites and refuses promotion eligibility for market-neutral carry

#### Scenario: Legacy carry adapter supplies a binary hedge
- **WHEN** a legacy paper adapter offers a binary event contract as the hedge for a linear perpetual funding-carry experiment
- **THEN** the stricter compatible-linear-hedge gate blocks market-neutral carry classification and promotion, records the dependency conflict, and permits reporting only as directional or funding-conditioned exploratory research

#### Scenario: Session feature adds no incremental evidence
- **WHEN** a session-boundary feature fails its frozen comparison with the same strategy without that feature
- **THEN** the result records the failed increment and does not characterize the session pattern as an independently validated strategy

### Requirement: Initial prediction-market candidate coverage

The initial prediction-market portfolio SHALL prioritize settlement-aware
probability nowcasting, final-window BRTI projection, and same-settlement
cross-strike probability-ladder consistency. Nowcasting SHALL evaluate trend,
volatility, distance to target, and observed settlement-window features against a
settlement-aware baseline. Final-window projection SHALL distinguish observed
samples from projections of the unobserved remainder. External-venue lead/lag and
order-flow hypotheses SHALL remain conditional on qualified causal book/trade
capture. Cross-horizon consistency SHALL remain an incubator until payoff and
settlement compatibility is demonstrated.

A ladder or cross-horizon discrepancy SHALL be called arbitrage only when the
recorded contract rules imply a nonnegative payoff in every covered outcome and
executable legs, fees, size limits, and execution uncertainty support the claimed
profit. A statistical disagreement without that payoff proof SHALL be labeled a
relative-value hypothesis.

#### Scenario: Final-window sample is not yet available
- **WHEN** a final-window candidate evaluates before the averaging window ends
- **THEN** its probability uses only samples available at decision time and projects the remaining samples without reading the final settlement label

#### Scenario: Two horizons settle on different observations
- **WHEN** a proposed cross-horizon trade uses contracts with different settlement windows and no all-outcome payoff proof
- **THEN** the report labels it a conditional relative-value experiment and does not claim guaranteed arbitrage

### Requirement: Benchmarks and rejected approaches remain visible

The portfolio SHALL retain no-trade, executable market-implied probability,
simple momentum, and naive basis-reversion benchmarks. Probability comparisons
SHALL distinguish forecast scoring from executable trade returns. The catalog
SHALL explicitly reject or quarantine naive zero-drift Black-Scholes or
Monte-Carlo mispricing claims, unfiltered mean reversion, candle-range maker
fills, binary contracts described as linear hedges, and pooled multi-asset
promotion. A rejected approach SHALL retain its reason and evidence and SHALL
require a new linked revision and explicit changed hypothesis to be reconsidered.

#### Scenario: Complex model only beats an omitted benchmark
- **WHEN** a candidate report lacks its frozen simple benchmark on the same eligible sample
- **THEN** the system marks incremental-value evidence incomplete and withholds promotion eligibility

#### Scenario: Rejected method is reconsidered
- **WHEN** research introduces a materially changed mean-reversion hypothesis after an earlier rejection
- **THEN** the new revision links to the original rejection and preserves the original result and reason

### Requirement: Research lifecycle does not grant execution authority

Each candidate revision SHALL expose a lifecycle state of `proposed`,
`waiting_for_data`, `ready_for_test`, `testing`, `evaluated`, `paper_candidate`,
`rejected`, or `parked`, with timestamped transitions and reasons. `ready_for_test`
SHALL require a frozen plan and passing candidate-specific data qualification;
`paper_candidate` SHALL require passing research evidence and SHALL mean eligible
for a separate paper-admission decision. These states SHALL NOT modify asset
registry modes, existing strategy gate status, account allocation, or live-order
authorization. A process SHALL be reported as running only when supported by
current job or worker evidence; stale evidence SHALL display as unknown/stale.

#### Scenario: Backtest passes all research gates
- **WHEN** a candidate obtains passing research evidence
- **THEN** its state can become `paper_candidate` while asset modes and existing paper/live admission controls remain unchanged

#### Scenario: Insufficient data is the remaining prerequisite
- **WHEN** a frozen candidate lacks its required book history
- **THEN** its state is `waiting_for_data` and its card identifies book collection and the measurable remaining requirement

## Model complexity

Complexity is high because strategy ranking and payoff classification depend on
multiple active contracts. Preserve the proposal's GPT-6 Astra/Claude Opus 5
allocation for economic assumptions and final evidence review; GPT-5.6 Terra or
Claude Sonnet 5 can implement bounded catalog/report work after contracts freeze.
Anthropic allocation is advisory. Escalate ambiguous payoff or hedge semantics;
lighter-model work must not alter economic gates.

## Checkpoint

This capability is specified for `crypto-strategy-research-program`; implementation
has not begun. The authoritative stage and next artifact are the OpenSpec CLI
status and the change's design/tasks checkpoint. On model replacement, read status,
the proposal, design, and dependency specs before continuing; retain completed
requirements and record any evidence-driven revision.
