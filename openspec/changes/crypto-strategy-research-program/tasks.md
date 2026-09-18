## 1. Prerequisites and implementation contract

- [ ] 1.1 Reconcile current code and unfinished tasks in `kxbtc15m-validation-rebuild`, `multi-asset-crypto-scalping`, and `strategy-lab-multi-account`; record the exact prerequisite for each first-wave candidate without duplicating an execution engine.
- [ ] 1.2 Record precedence of the causal/settlement/perp-isolation contracts over legacy fixed win-rate floors, binary funding hedges and spent holdout results; add an auditable conflict reason for the legacy carry adapter.
- [ ] 1.3 Map each new capability requirement to an implementation seam and verification case; identify which work can proceed while native data accumulates and which runs remain data-blocked.
- [ ] 1.4 Freeze the implementation scope as BTC E1/P1/P2 first, E2/E3 conditional, ETH separately qualified later; keep P3-P5/E4-E5 at catalog/data-readiness only until their incubator gates pass and a later implementation plan is frozen.

## 2. Candidate catalog and lifecycle

- [ ] 2.1 Add typed, versioned candidate records with stable ID, rank, disposition, domain/asset/instrument/cadence, mechanism, entry/exit hypothesis, benchmark, inputs, falsification rule, gate and predecessor revision.
- [ ] 2.2 Populate E1-E5, P1-P5, B1-B4 and R1-R5 from design D1; represent P2 pullback and level-break as separately counted variants and P5 as blocked pending compatible linear hedge economics.
- [ ] 2.3 Implement candidate transitions `proposed`, `waiting_for_data`, `ready_for_test`, `testing`, `evaluated`, `paper_candidate`, `rejected` and `parked`, with durable timestamps and reasons.
- [ ] 2.4 Keep candidate states, research run lifecycle, evidence verdicts, strategy gate status and asset execution modes as separate fields; require a frozen plan plus passing data gates for `ready_for_test`.
- [ ] 2.5 Resolve candidate instruments through registry/discovery snapshots and expose missing listings or unsupported cadences as prerequisites; never infer tickers or authorize execution from catalog rank.
- [ ] 2.6 Verify invalid transitions, rejected-candidate revision lineage, benchmark retention and unchanged strategy/asset execution authority with focused catalog tests.

## 3. Additive persistence and immutable evidence

- [ ] 3.1 Add research candidate revisions, experiment plans, trial records, run/checkpoint records and evidence-report references using existing manifest and Strategy Lab identities where available.
- [ ] 3.2 Implement additive idempotent migrations, documented backup/restore instructions and non-destructive rollback behavior; verify fresh and populated SQLite upgrades preserve existing records.
- [ ] 3.3 Implement canonical serialization and content hashes for frozen plans/manifests/configuration; reject in-place edits and create linked revisions for changes.
- [ ] 3.4 Persist process identity, start/end/heartbeat, exit status, last checkpoint and reason for completed/failed/cancelled/inconclusive runs; represent stale worker evidence as unknown/stale.
- [ ] 3.5 Verify restart recovery does not silently rerun experiments, erase negative evidence, invent a healthy worker or mutate a completed manifest after backfill.

## 4. Data qualification and provenance

- [ ] 4.1 Audit existing feed fields for event time, receipt/availability time, timestamp precision, sequence integrity, units and source-native/reconstructed classification; report missing semantics without fabricating timestamps.
- [ ] 4.2 Add a versioned qualification policy containing coverage, usable overlap, independent day/settlement counts, sample spacing, maximum age/skew/gaps, liquidity/depth, spread and regime thresholds; incomplete policies return unknown rather than pass.
- [ ] 4.3 Implement Q0 identity/economics checks for registry mapping, contract predicates, target availability, averaging/rounding rules, price/quantity units, fees and margin/funding conventions.
- [ ] 4.4 Implement Q1 completed-bar/as-of checks and candidate-specific intersection of eligible source windows; exclude incomplete bars and lookbacks spanning unsupported gaps.
- [ ] 4.5 Implement Q2 native-index settlement qualification with known outcome labels and fresh event quotes; retain reconstructed datasets as diagnostic and preserve existing paper-fill restrictions.
- [ ] 4.6 Implement Q3 final-window sample coverage and missing-contribution checks against the actual contract functional; do not substitute spot or interpolate missing native observations as observed samples.
- [ ] 4.7 Implement Q4 perp executable-price/depth, multiplier normalization, reference/mark distinction, funding publication/cashflow timing and margin/liquidation metadata checks.
- [ ] 4.8 Implement Q5 microstructure integrity checks for sequencing/resynchronization, original time precision, measured latency and clock error; keep sparse-book or candle-only inputs unqualified for fast lead/lag and maker claims.
- [ ] 4.9 Implement Q6 synchronized multi-leg coverage, compatible payout predicates, available depth/capital and leg-risk prerequisites; a reference index is not an executable hedge.
- [ ] 4.10 Generate immutable per-scope qualification manifests with eligible/excluded windows, reason counts, pass/fail/unknown gates, measured numerator/target and remaining collection actions.
- [ ] 4.11 Verify delayed arrivals, revisions, native versus reconstructed inputs, short source overlap, asset-specific gaps, incompatible ladder rules, second-level timestamp ties and publication-versus-realized funding fixtures.
- [ ] 4.12 Use a data-quality-only pilot to freeze initial candidate thresholds and document actual feed/settlement cadence before inspecting strategy outcomes; preserve the manual foreground collection policy.

## 5. Frozen experiments and chronological evaluation

- [ ] 5.1 Add complete ExperimentPlan validation for candidate/scope, manifests, features/labels, calibration, limited variants, benchmark, entry/exit/sizing, fees/fills, folds, embargo, sample/power criteria, primary metric, uncertainty, multiplicity and stopping policy.
- [ ] 5.2 Add a durable trial ledger counting parameter/feature variants, asset/cadence/horizon alternatives, failed/abandoned attempts and holdout inspections; enforce the initial maximum of two substantive variants per candidate per wave.
- [ ] 5.3 Preserve E1/E2 and P2/P3 family relationships and freeze the complete confirmation claim set; reject budget/inference changes without a linked plan revision and new untouched evidence.
- [ ] 5.4 Extend the existing walk-forward coordinator with label/position overlap purging and horizon-aware embargo; retain the initial BTC event 28-day train, one-day minimum embargo and 14-day test geometry without treating its approximately 71-day minimum as proof of sufficiency.
- [ ] 5.5 Verify fresh broker/cash/positions/risk guards per test fold, causal feature warmup and prior-outcome-only calibration; training halts or open positions must not leak into test state.
- [ ] 5.6 Implement untouched confirmation-window reservation after finalist freeze, an initial target of at least 28 eligible days subject to a preregistered sample/power rule, and explicit exclusion of spent/inspected holdouts.
- [ ] 5.7 Prevent outcome-based early stopping and unregistered repeated looks; persist inspection history and downgrade uncovered looks to nonconfirmatory evidence.
- [ ] 5.8 Verify missing plan fields, post-outcome edits, overlapping labels, insufficient confirmation data and attempted holdout reuse fail closed with actionable reasons.

## 6. Causal execution and economic accounting

- [ ] 6.1 Connect research replay to existing prediction/perp engines and contexts; apply modeled latency and require strictly later eligible fill evidence with observable depth rather than instantaneous decision-quote fills.
- [ ] 6.2 Verify YES/NO price conventions, fixed-point quantities, entry and early-exit fees, schedule versions and rounding against known cashflow examples.
- [ ] 6.3 Verify perp per-contract/index-unit conversion, notional entry/exit fees, realized funding timing, mark/index divergence and margin/liquidation exposure using the existing separate perp ledger.
- [ ] 6.4 Keep maker orders unfilled without observed execution or a separately validated queue/partial-fill model; record staleness, inadequate depth and missing evidence as explicit no-trade reasons.
- [ ] 6.5 Add frozen base/adverse execution scenarios for measured latency, slippage/spread, reduced depth and relevant funding-sign changes; report their assumptions and results independently.
- [ ] 6.6 Add reusable multi-leg replay support only as needed for conditional E3, including non-simultaneous fills, incomplete legs, residual exposure and frozen unwind costs; do not enable P4/P5 through this work.
- [ ] 6.7 Verify no midpoint/mark-only profit recognition, no candle-range maker fills, no same-event fills and no complete arbitrage profit after a failed leg.

## 7. First-wave candidates and benchmarks

- [ ] 7.1 Implement frozen no-trade, market-implied event probability, simple momentum and naive basis-reversion benchmark configurations using identical eligible samples and cost/capital conventions.
- [ ] 7.2 Adapt E1 to the existing settlement-probability strategy with native index, known target/window, causal volatility and distance/time features; keep the simple baseline and one registered trend/volatility variant separately identifiable.
- [ ] 7.3 Record E1 probabilities on the frozen eligible decision grid for BUY and HOLD decisions, preserving source timestamps and model/calibration versions; distinguish forecast-scoring and filled-trade populations.
- [ ] 7.4 Implement P1 executable perp/reference-basis features and a frozen convergence/invalidation rule; separate funding from price PnL and label nontradable-index comparisons as single-leg directional/basis risk.
- [ ] 7.5 Implement P2's registered pullback/resumption variant with fixed causal lookback, volatility regime, entry horizon and invalidation condition on the perp strategy seam.
- [ ] 7.6 Implement P2's registered level-break continuation variant with only prior level/volume evidence and the same economics conventions; preserve the failed legacy binary strategy's historical status.
- [ ] 7.7 Add known-answer fixtures for E1 probability/settlement behavior, P1 unit-normalized basis and persistent divergence, P2 causal trend/level formation, and funding-estimate availability.
- [ ] 7.8 Run first-wave development only for qualified scopes after sections 4-6 pass; retain blocked or insufficient candidates and compare every completed variant with its frozen benchmark.

## 8. Conditional prediction extensions and incubator boundaries

- [ ] 8.1 Evaluate E2 prerequisites against Q0/Q2/Q3 and executable-latency evidence; record a blocked checkpoint if they fail and schedule E2 implementation only after they pass.
- [ ] 8.2 After task 8.1 passes, implement observed-plus-projected final-window probability using the exact averaging/tie/rounding functional; preserve an independent E2 gate and its E1 family membership.
- [ ] 8.3 Verify E2 excludes future samples and final labels, rejects unsupported missing windows and loses apparent edge when a later executable quote or expiry buffer prevents entry.
- [ ] 8.4 Evaluate E3 prerequisites against Q0/Q6 and the required multi-leg event/fill evidence; record incompatible predicates, stale legs or insufficient depth as blockers before implementation.
- [ ] 8.5 After task 8.4 passes, implement ladder probability-consistency diagnostics and an explicit all-outcome payoff verifier; label discrepancies as relative value unless executable complete-leg costs support the payoff claim.
- [ ] 8.6 Verify E3 boundary inclusivity, unequal expiry/statistics, fee-erased spreads, size constraints and one-leg failure; register any qualified experiment separately from E1/E2.
- [ ] 8.7 Publish readiness-only cards and reopening criteria for P3 boundary effects, P4 relative strength, E4 lead/lag and E5 cross-horizon consistency; do not schedule their strategy implementation before their gates and a subsequent frozen implementation plan are complete.
- [ ] 8.8 Keep P5 funding carry blocked until an explicit compatible linear hedge, financing/borrow, rebalancing, execution and residual-basis design passes its independent prerequisites; verify a binary hedge cannot clear this gate.

## 9. Statistical evaluation and research verdicts

- [ ] 9.1 Implement net expectancy/PnL and cost decomposition, drawdown, exposure/turnover, independent-day/settlement counts, coverage, fold/regime metrics, concentration and execution-quality summaries.
- [ ] 9.2 Implement comparable-sample Brier/log-loss/reliability reporting for all eligible probability decisions and paired incremental benchmark metrics; repeated predictions within a contract do not add independent outcomes.
- [ ] 9.3 Implement preregistered session/day-block uncertainty with settlement-episode clustering, preserved simultaneous cross-asset dependence and longer-block sensitivity; insufficient independent evidence returns inconclusive.
- [ ] 9.4 Implement Holm correction with a 5% familywise error budget over the finite frozen confirmation batch's candidate/asset/cadence primary claims; disclose all development trials and keep secondary metrics descriptive.
- [ ] 9.5 Compose inherited promotion gates with candidate-specific power/sample, uncertainty-adjusted expectancy, benchmark improvement, concentration/drawdown and stress acceptance; missing metrics or unresolved data/execution failures cannot pass.
- [ ] 9.6 Verify known correction examples, correlated repeated observations, missing confidence intervals, high-win-rate negative expectancy, aggregate/asset disagreement and independent prediction/perp failures.
- [ ] 9.7 Freeze qualified finalists and run confirmation only when reserved future data qualifies; preserve every rejection/inconclusive result and require new future evidence for outcome-informed revisions.

## 10. Reports, downloads and dashboard integration

- [ ] 10.1 Build an immutable evidence report containing plan/manifest/code hashes, qualification gates, trial ledger, decisions, trades/fills, funding, costs, exclusions, diagnostics, source references and reproducibility instructions.
- [ ] 10.2 Add JSON, human-readable Markdown/HTML and tabular audit exports; redact credentials/account identifiers and disclose raw-data retention/redistribution restrictions instead of claiming unavailable captures are included.
- [ ] 10.3 Connect the existing Progress/Strategy Lab presentation to research summaries showing hypothesis, rank, lifecycle, data prerequisites, remaining actions, benchmark/net results, uncertainty and stress results.
- [ ] 10.4 Show failed, rejected, cancelled and prior runs alongside successful runs; distinguish capture health, worker state, software-test completion, data readiness and economic evidence with explicit percentage denominators.
- [ ] 10.5 Reuse existing job evidence for queued/running/completed/failed/unknown-stale status and display the last durable checkpoint; do not add an unattended scheduler or a second process manager.
- [ ] 10.6 Verify exports reproduce report totals and preserve original manifests after backfill; verify stale worker and 100%-duration-but-failed-quality dashboard scenarios render honestly.

## 11. Paper handoff and integration verification

- [ ] 11.1 Generate a paper-review handoff only for independently passing candidate scopes, listing remaining asset/strategy admission, execution-safety and operator-review gates; do not mutate modes, allocations or live authority.
- [ ] 11.2 Verify research `paper_candidate` state cannot bypass source-native admission, separate perp gates, compatible hedge requirements or existing Strategy Lab execution controls.
- [ ] 11.3 Run the relevant existing and new causality, accounting, qualification, migration, governance and reporting tests plus project formatting/lint checks; attach exact commands/results to the checkpoint.
- [ ] 11.4 Run one small reproducible fixture-backed end-to-end experiment from frozen manifest through report/export, including a deliberate failed gate and stale-worker recovery; fixture success is software evidence only.
- [ ] 11.5 Reproduce one qualified empirical research result from its immutable bundle when data exists, or record the exact unmet data gate without inventing a completed empirical test.
- [ ] 11.6 Perform a focused rollback check proving research registrations/routes can be disabled while raw observations, plans, trial history and existing execution protections remain intact.

## 12. Documentation, model complexity and checkpoint

- [ ] 12.1 Document candidate mechanisms, falsification rules, per-scope collection needs, experiment/reproduction commands, interpretation of readiness percentages and the difference between software completion and strategy evidence.
- [ ] 12.2 Preserve the high-complexity allocation: GPT-6 Astra high/xhigh or advisory Claude Opus 5 for causal/economic/inference contracts and final evidence review; GPT-5.6 Terra or advisory Claude Sonnet 5 for bounded implementation after those contracts freeze; lighter models only for mechanical work.
- [ ] 12.3 Record escalation triggers for ambiguous payoff/funding/timestamp semantics, new fill assumptions, holdout changes or two failures of one validation scenario; record actual selected models without claiming advisory Anthropic work ran.
- [ ] 12.4 Maintain a durable checkpoint after each work group with completed tasks, unresolved gates, evidence locations, verification, next resumable action and exact dependency blockers; resume from existing plans rather than regenerating them after a model switch.
- [ ] 12.5 Before implementation handoff, read `openspec status --change crypto-strategy-research-program --json`, this proposal/design/all three specs and dependency contracts, then use the apply skill for the first unfinished task; artifact completion does not start capture or experiments.
- [ ] 12.6 Re-run `openspec validate crypto-strategy-research-program`, record its result and the remaining implementation/research gates, and keep this checklist open for data-blocked conditional work rather than marking it complete on schedule alone.

Planning checkpoint: proposal, design, all three capability specs and this task artifact are written;
implementation has not begun and every implementation checkbox remains unchecked. The task-stage
CLI contract and all dependency artifacts were read. `openspec validate crypto-strategy-research-program`
passed, and CLI status reports all planning artifacts complete. The first implementation action
is task 1.1; the unresolved numerical data/power thresholds and compatible linear hedge remain as
documented in the design. No collector, research run, paper process or live order is started by
completion of these planning artifacts.
