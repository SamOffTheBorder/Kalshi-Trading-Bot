## ADDED Requirements

### Requirement: Freeze experiments before holdout evaluation

Each experiment SHALL persist an immutable plan before accessing its holdout
outcomes. The plan SHALL identify hypothesis and candidate revision, scope,
dataset manifests, features, training/calibration method, parameter search space,
selection objective, benchmarks, eligibility filters, entry/exit/sizing rules,
cost/fill models, fold boundaries, purge/embargo rules, minimum evidence,
primary metric, uncertainty procedure, multiple-testing family/budget, and
pass/fail/inconclusive criteria. The run SHALL record code/configuration versions
and random seeds where applicable. Any outcome-informed change SHALL create a
linked experiment revision and require untouched evidence for confirmatory claims.

#### Scenario: Parameter threshold changes after seeing holdout losses
- **WHEN** an operator revises an entry threshold after inspecting holdout results
- **THEN** the registry creates a linked exploratory revision, preserves the original loss, and does not reuse that inspected holdout as untouched confirmation

#### Scenario: Holdout run lacks a frozen fee model
- **WHEN** a confirmatory run is requested without a complete frozen cost model
- **THEN** preflight rejects confirmatory status and records the missing plan field

### Requirement: Purged walk-forward evaluation and isolated folds

Evaluation SHALL train and calibrate only on data preceding each test fold,
purge training labels whose information intervals overlap evaluation, and apply
the frozen embargo rule appropriate to outcome and holding horizons. Feature
history from before a fold SHALL be usable only under causal availability rules.
Each out-of-sample fold SHALL initialize its own broker, cash, positions, and risk
guards. Evaluation SHALL preserve chronological order, report each fold, and keep
an untouched final confirmation window separate from development selection.

#### Scenario: Training label settles inside the test interval
- **WHEN** a training observation's label is resolved after the test fold starts
- **THEN** that observation is purged from training according to its overlapping information interval

#### Scenario: Training broker has an open losing position
- **WHEN** the corresponding out-of-sample fold starts
- **THEN** the test broker begins with its declared initial state and does not inherit the training position, cashflow, or halted guard state

### Requirement: Realistic cost and execution evidence

Every result SHALL account for executable side-specific entry and exit prices,
spread, slippage/depth, fee tiers and rounding, latency, partial fills, cancels,
and failed orders as applicable. Event contracts SHALL retain YES/NO-side
accounting and both-leg fees for early exits. Perpetuals SHALL additionally account
for funding cashflows, margin use, mark/index divergence, liquidation exposure,
and hedge/borrow/rebalance costs where applicable. Orders SHALL fill only on
later eligible evidence after the decision and modeled latency. Maker fills
SHALL require observed fills or a validated queue/partial-fill model; multi-leg
tests SHALL model non-simultaneous execution, incomplete legs, and unwind costs.
Base-case and adverse cost/latency/liquidity scenarios SHALL be frozen in the plan
and reported separately.

#### Scenario: Signal observes a quote at decision time
- **WHEN** a strategy submits a simulated order using that quote
- **THEN** the simulator cannot assume an instantaneous fill at the observed price and evaluates later eligible events under its frozen latency model

#### Scenario: First arbitrage leg fills but second leg does not
- **WHEN** a multi-leg simulation cannot execute its remaining leg
- **THEN** it records residual exposure and the frozen unwind or holding policy with its costs rather than recognizing the full quoted spread as profit

### Requirement: Trial accounting and multiple-hypothesis control

The registry SHALL count all attempted candidates, feature variants, parameter
searches, and inspected confirmatory runs within a declared hypothesis family,
including failures and abandoned variants. Each family SHALL freeze its trial
budget and selection-adjusted inference procedure before confirmatory evaluation.
Exploratory findings SHALL be labeled exploratory. Confirmatory promotion SHALL
apply the frozen multiplicity adjustment or independently held-out selection
procedure, account for repeated looks under a frozen sequential policy, and
report the number of attempted and selected variants. Increasing the budget or
changing the procedure SHALL create a revised plan and require untouched evidence.

#### Scenario: One winner is selected from many variants
- **WHEN** a family tests 50 parameter variants and reports its best performer
- **THEN** its report discloses all 50 trials and applies the frozen selection-control procedure rather than treating the winner as a single independent test

#### Scenario: Operator repeatedly checks growing holdout performance
- **WHEN** confirmatory evidence is inspected more often than the frozen policy allows
- **THEN** the run is marked nonconfirmatory for promotion unless a preregistered sequential method covers those looks

### Requirement: Per-scope evidence and independent promotion gates

Research reports SHALL include net expectancy, net PnL and cost decomposition,
drawdown, exposure/turnover, trade and independent-day counts, coverage, fold and
regime results, fill/cancel/partial-fill rates, adverse-selection metrics, and
day-blocked uncertainty estimates. Probability strategies SHALL additionally
report Brier score, calibration, and incremental performance against their frozen
probability benchmark on a comparable sample. Day blocking SHALL preserve
within-day dependence and the frozen uncertainty procedure SHALL handle any
remaining dependence appropriate to holding/settlement horizons.

Promotion eligibility SHALL require candidate-specific evidence thresholds,
positive cost-adjusted expectancy supported by the frozen selection-adjusted
uncertainty gate, benchmark improvement, stress acceptance, and no unresolved
data/execution failures. Sparse or inconclusive evidence SHALL remain
inconclusive. Results SHALL be separate by asset, instrument, cadence, and
prediction/perpetual domain; pooled portfolio gains or legacy v2 metrics SHALL
NOT promote a failing or untested scope. Research eligibility SHALL feed existing
admission/promotion controls and SHALL NOT mutate live authority.

#### Scenario: Positive aggregate hides a failing asset
- **WHEN** pooled returns are positive and an individual asset's frozen evidence gate fails
- **THEN** the asset remains ineligible and its failed result is shown alongside the aggregate

#### Scenario: High win rate has negative expectancy
- **WHEN** a candidate wins frequently but loses money after full costs or fails the uncertainty gate
- **THEN** its report refuses promotion eligibility regardless of win rate

#### Scenario: Binary prediction passes while perp evidence is absent
- **WHEN** the prediction strategy passes all research gates and its related perp has no independent passing evidence
- **THEN** the perpetual remains unqualified and the report names its missing evidence

### Requirement: Permanent negative results and downloadable audit bundle

Every started run SHALL retain a durable identity and terminal status of completed,
failed, cancelled, or inconclusive when it terminates, with reason and timestamps.
Rejected hypotheses, negative metrics, exceptions, abandoned variants, and prior
revisions SHALL remain discoverable alongside successful results. A report SHALL
export its frozen plan, manifests/hashes, qualification results, metrics, trial
ledger, decision/trade/fill audit records, diagnostics, and source references or
retrieval instructions. Secret credentials SHALL be redacted. Where raw data is
subject to retention or redistribution constraints, the report SHALL state the
limitation and preserve the identifiers and reproducibility impact rather than
claiming a complete raw-data export.

#### Scenario: Failed experiment is rerun successfully
- **WHEN** a later revision completes after an earlier execution failure or negative result
- **THEN** both runs remain accessible with their relationship, original statuses, and original evidence

#### Scenario: Evidence bundle is downloaded
- **WHEN** an operator exports a candidate's completed test
- **THEN** the bundle identifies the precise plan, data, code, scope, costs, decisions, and trial family needed to reproduce or audit the result without including credentials

### Requirement: Durable research checkpoints and process status

The experiment registry SHALL persist the current stage, completed work, remaining
qualification or review actions, unresolved assumptions, evidence locations,
verification status, and next resumable action. Process status SHALL distinguish
queued, running, completed, failed, and unknown/stale using current job evidence.
A restart or model handoff SHALL resume from persisted state without regenerating
completed plans or silently rerunning tests. Reports SHALL distinguish research
progress, data readiness, test completion, and evidence quality; a percentage
SHALL have a documented denominator and SHALL NOT imply profitability.

#### Scenario: Worker disappears during evaluation
- **WHEN** persisted run state says running but its worker evidence becomes stale
- **THEN** the dashboard exposes unknown/stale execution status and the last durable checkpoint rather than declaring success or continued healthy execution

#### Scenario: Research work is handed to another model
- **WHEN** a new model resumes the program
- **THEN** it reads the persisted stage and frozen decisions and continues the next unfinished action without replacing completed experiments

## Model complexity

Complexity is high, with evaluation validity the principal risk. The proposal's
GPT-6 Astra/Claude Opus 5 allocation owns leakage review, inference, execution
assumptions, and final gate review. GPT-5.6 Terra/Claude Sonnet 5 can implement
bounded frozen contracts; Anthropic execution remains advisory unless selected
by the user. Escalate changed holdout boundaries, ambiguous costs/payoffs, a new
execution assumption, or two failures of the same validation scenario. Lighter
models must not change inference or promotion policy.

## Checkpoint

The governance specification is complete for artifact review, with no experiments
run and no implementation begun. Read `openspec status --change
crypto-strategy-research-program --json`, the proposal, design, all three new
capability specs, and dependency contracts before resuming through the next ready
artifact. The change's design/tasks checkpoint records final artifact validation
and remaining decisions; research completion is not implied by artifact completion.
