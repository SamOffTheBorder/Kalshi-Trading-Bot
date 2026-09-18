## 1. Safety baseline and integration inventory

- [x] 1.1 Inventory existing BTC paper-loop, crypto registry, Kalshi public/margin clients, sports feasibility artifacts, emergency-control state, dashboard queries, and storage tables; document exact reuse versus replacement seams.
- [x] 1.2 Add a `PaperExecutionGuard` contract that validates paper-only mode, demo environment for authenticated reads, local paper ledger target, and dependency injection excluding live order/amend/cancel clients.
- [x] 1.3 Add startup tests proving every new paper entry point refuses `PAPER_TRADING=false`, production authenticated configuration, missing confirmation, unsafe database target, and a mutating client.
- [x] 1.4 Define versioned lifecycle states (`disabled`, `observe`, `backtest`, `shadow`, `paper`, `blocked`) and a single asset/domain/candidate identity format.
- [x] 1.5 Add schema migration/version compatibility tests confirming existing Kalshi, BRTI, sports research, and BTC paper records remain readable without mutation.

## 2. External market-data storage and provenance

- [x] 2.1 Add additive storage models/migrations for raw data artifacts, artifact checksums/content hashes, source instrument mappings, normalized bars, normalized aggregate trades, source quality/gaps, and immutable dataset manifests.
- [x] 2.2 Define raw-artifact on-disk layout, content-addressing, retention rules, and safe path validation; keep large raw files outside source control and record only metadata/manifests in SQLite.
- [x] 2.3 Define typed source, market-type, quote-currency, timestamp-unit, quality-status, and source-role models; prohibit implicit source mixing and quote-currency conversion.
- [x] 2.4 Implement idempotency keys for artifacts and normalized observations, including provider revision/parser version, and test duplicate/revision behavior.
- [x] 2.5 Implement UTC timestamp parsing/normalization with observed, available, retrieved, open, and close times; add tests for seconds/milliseconds/microseconds, ordering, and incomplete bars.
- [x] 2.6 Implement coverage, gap, source-lag, rejected-row, and symbol-mapping report builders with JSON and dashboard-ready summaries.
- [x] 2.7 Add fixtures and migration tests for malformed CSV/ZIP/JSON, checksum mismatch, empty file, invalid prices/sizes, time-unit mismatch, duplicate trades, and source revision.

## 3. Primary exchange-native crypto history

- [x] 3.1 Define the BTC/ETH/SOL/XRP primary mappings for Binance spot and USD-M futures, including native symbols, venue/quote currency, supported cadence, archive path, and expected dataset schema.
- [x] 3.2 Implement a read-only Binance public archive client that resolves daily/monthly artifacts and sidecar checksums without hard-coding unverified file availability.
- [x] 3.3 Implement checksum-verified download/cache of spot OHLCV and aggregate trades with resumable/idempotent foreground import behavior.
- [x] 3.4 Implement checksum-verified download/cache of USD-M futures OHLCV, aggregate trades, and any published funding inputs required by the selected strategies.
- [x] 3.5 Normalize Binance source artifacts into typed observations without forward fills; explicitly record source timestamp precision and any unavailable interval.
- [x] 3.6 Build a bounded CLI to discover, fetch, validate, normalize, and report a requested primary-source asset/time/cadence window; ensure it cannot submit an exchange order.
- [x] 3.7 Add deterministic fixture tests for BTC, ETH, SOL, and XRP source mappings, archive URLs, checksums, schemas, partial downloads, revision detection, and causal availability.

## 4. Secondary and manual comparison data sources

- [x] 4.1 Define Coinbase BTC-USD, ETH-USD, SOL-USD, and XRP-USD secondary mappings, including documented incomplete-candle treatment and rate-limit behavior.
- [x] 4.2 Implement a read-only, bounded Coinbase candle import adapter that preserves raw responses and reports missing buckets rather than filling them.
- [x] 4.3 Implement cross-source comparison reports for aligned source-specific returns, timing, gaps, price divergence, and symbol/quote-currency compatibility; keep source series separate.
- [x] 4.4 Implement a manual TradingView CSV import adapter requiring operator-declared symbol, interval, timezone, export time, quote currency, and mapping review; store it only as `manual_comparison` provenance.
- [x] 4.5 Add tests proving a TradingView artifact cannot become the sole approved primary manifest, cannot overwrite primary data, and fails mapping validation when metadata is incomplete.
- [x] 4.6 Document source availability, geographic/network limitations, provider terms-review checklist, stablecoin/USD treatment, and a vendor-adapter path for a later approved paid provider.

## 5. Frozen dataset manifests and data-quality admission

- [x] 5.1 Implement immutable manifest creation that pins raw artifact hashes, normalized partitions, source mappings, parser/feature versions, filtering rules, time range, code revision, and configuration hash.
- [x] 5.2 Implement manifest reader validation that fails closed on missing, rejected, changed, source-misaligned, or out-of-range artifacts.
- [x] 5.3 Define per-asset/cadence minimum data coverage, maximum gap, source-lag, and cross-source discrepancy policies as explicit versioned configuration—not embedded constants.
- [x] 5.4 Implement data-quality and source-alignment verdicts for each BTC/ETH/SOL/XRP asset, including a visible reason for no data, stale data, incompatible index, or unsupported venue.
- [x] 5.5 Add end-to-end tests constructing a manifest from fixture artifacts, reproducing a report, then verifying that a later artifact revision or missing partition blocks reuse.
- [x] 5.6 Produce and review the first non-promotional BTC/ETH/SOL/XRP coverage and source-comparison report; record observed gaps without altering historical data. (`SCRATCHPAD/crypto-coverage-source-report.json` records Binance spot/perp coverage for all four assets, Coinbase overlap for BTC/ETH, missing secondary coverage for SOL/XRP, and observed gaps; all results are diagnostic-only.)

## 6. Crypto registry, Kalshi discovery, and settlement alignment

- [x] 6.1 Narrow the shipped active crypto registry to BTC, ETH, SOL, and XRP; retain historical records for other assets as archived/non-active and update registry tests.
- [x] 6.2 Add explicit prediction and perpetual mappings, source roles, lifecycle state, and per-asset paper-admission metadata to the registry without granting paper authorization by configuration alone.
- [x] 6.3 Generalize Kalshi prediction-market discovery across the four assets and supported cadences; validate market shape, rules, liquidity, open interest, spread, depth, status, and freshness.
- [x] 6.4 Generalize authenticated read-only Kalshi margin discovery across the four assets; persist multiplier, minimum order size, tick size, margin/leverage parameters, funding availability, reference index, and freshness.
- [x] 6.5 Implement contract settlement/source alignment checks among external source, BRTI/index observations, Kalshi market rules, event contract metadata, and perpetual metadata; unknown alignment must block paper admission.
- [x] 6.6 Add fixtures/tests for missing/renamed series, malformed markets, stale snapshots, one-sided quotes, wrong contract shape, absent spot feed, incompatible settlement index, and perps without sufficient metadata.
- [x] 6.7 Update dashboard/query models to distinguish configured, discovered, eligible, source-aligned, shadow, paper, blocked, and archived assets per domain/cadence.

## 7. Underlying strategy research and reproducible backtests

- [x] 7.1 Define feature interfaces for source-specific 1-minute, 15-minute, and 60-minute BTC/ETH/SOL/XRP spot/perpetual features, preserving availability timestamps and no-incomplete-bar semantics.
- [x] 7.2 Implement chronological rolling/expanding walk-forward folds with a purge/embargo at least equal to maximum lookback plus prediction horizon.
- [x] 7.3 Implement asset-isolated underlying backtests with fixed train/validation/holdout windows, seeds, model/feature/execution config hashes, and frozen manifests. (`backtest/underlying.py` freezes a single-use plan hash, enforces purge windows, records lineage, and reports train/validation/holdout metrics.)
- [x] 7.4 Implement predeclared baselines: no-trade after cost, naïve/market baseline, and a simple non-LLM signal baseline appropriate to each candidate.
- [x] 7.5 Extend prediction-contract backtests to consume external underlying features while retaining causal Kalshi quote/rule/outcome execution and source-alignment blocking. (`BacktestEngine`/`run_validation_arms` accept causal `UnderlyingFeatures` and HOLD when aligned inputs are unavailable or unknown.)
- [x] 7.6 Extend perpetual backtests to use the independent linear ledger with bid/ask, multiplier, fees, realized funding, margin, leverage, liquidation-distance, and cost/fill reports. (`backtest/perp_ledger.py::simulate_perp_trade` is side-aware, causal, fee/funding-aware, and rejects unsafe leverage/quotes.)
- [ ] 7.7 Implement report generation for coverage, sample count, calibration/Brier where applicable, expectancy, confidence interval, realised versus modeled costs, fills/rejections, drawdown, funding, and liquidation risk, separated by asset/cadence/domain.
- [x] 7.8 Implement the worst-component gate so pooled or aggregate results cannot promote an asset/cadence/domain that fails an individual data, economics, or risk threshold. (`ComponentGateResult` is evaluated independently by `promotion_gate.py`; a pooled pass cannot override a failed component.)
- [x] 7.9 Preserve LLM boundaries in backtests: accept only captured allowlisted evidence hashes, exclude uncited/untracked output, and prohibit post-holdout threshold/model changes without a new holdout. (Underlying signal evidence hashes are allowlist-checked and holdout plans are single-use.)
- [x] 7.10 Add known-answer/regression tests for BTC/ETH/SOL/XRP source selection, unavailable inputs, no look-ahead, fold isolation, BRTI/index alignment, per-domain accounting, and aggregate-pass rejection. (Registry/source-alignment/perp-isolation coverage plus new causal underlying, external-feature, perp-simulator, and worst-component tests.)

## 8. Shared paper-run orchestration and binary prediction migration

- [x] 8.1 Define shared, typed audit envelopes for paper run, decision, risk decision, quote/data reference, order attempt, fill/rejection, position event, heartbeat, reconciliation event, and final report.
- [x] 8.2 Add additive storage/migrations for paper runs and domain-neutral audit events; link all events to strategy/model/data-manifest/risk-policy and source snapshot hashes.
- [x] 8.3 Implement a foreground `run_paper` command with explicit `--domain`, `--assets`, `--duration`, strategy/config/report IDs, and safe defaults; add SIGINT/SIGTERM clean shutdown.
- [x] 8.4 Implement preflight that verifies the paper guard, registry lifecycle, fresh discovery/eligibility/source alignment, frozen validation/paper-admission report, data availability, and risk policy before a run starts.
- [x] 8.5 Refactor the existing KXBTC15M loop behind the shared prediction adapter while preserving its conservative limit fill, fees, signal persistence, official settlement, and restart recovery behavior. *(New `PredictionPaperAdapter` wraps `PaperBroker` behind the shared envelope; `scripts/run_paper_trading.py` now warns it is a one-release shim pointing at `scripts/run_paper.py`. Live BRTI-feature wiring into the new adapter's `StrategyFn` is deferred to strategy selection.)*
- [x] 8.6 Generalize the prediction adapter for separately admitted BTC/ETH/SOL/XRP contracts without using a stale/guessed ticker or pretending that an unlisted asset is eligible.
- [x] 8.7 Implement shadow mode that records every decision/risk outcome and observable would-fill without creating paper fills or positions.
- [x] 8.8 Implement durable restart reconciliation for binary positions and run-state heartbeats; block new entries on orphaned, ambiguous, stale, or unresolved state.
- [x] 8.9 Add unit/integration tests for preflight refusal, lifecycle transitions, domain routing, signal/HOLD audit persistence, interrupt handling, restart settlement, stale quote rejection, and legacy BTC output parity.

## 9. Perpetual paper execution

- [x] 9.1 Add perpetual-specific paper order, fill, position, mark, funding, margin, bracket, liquidation, and reconciliation storage models/migrations; do not overload binary `SimulatedTrade` semantics.
- [x] 9.2 Implement a perpetual paper adapter with signed long/short quantity, causal side-aware bid/ask fills, tick/minimum-size validation, frozen fee schedule, multiplier, and quote-reference persistence.
- [x] 9.3 Implement mark-to-market equity, realized/unrealized PnL, collateral/free-margin, leverage, and liquidation-distance calculations with explicit conservative rounding rules.
- [x] 9.4 Implement realized funding accrual using causal Kalshi funding history; show funding estimates as non-realized risk information only.
- [x] 9.5 Implement bracket validation, simulated stop-loss/take-profit exits, mark/quote-gap handling, forced-close/liquidation simulation, and emergency halt integration. *(`perp_paper.py`: `open()` now requires a directionally-valid bracket + leverage-cap check; `evaluate_perp_step`/`adapter.step` handle halt > liquidation > gapped-stop > bracket precedence; `close_perp_position` does side-aware exit accounting; missing mark → reconciliation event, never a fabricated close.)*
- [x] 9.6 Implement fresh perpetual discovery/metadata/mark/funding admission for BTC, ETH, SOL, and XRP, with clear no-entry/reconciliation reasons. *(`execution/perp_admission.py`: `evaluate_perp_admission` combines active-asset check, fresh eligible `PerpDiscovery` snapshot, fresh mark, realized-funding coverage (estimate never gates), frozen report, and paper mode into an explicit reason string.)*
- [x] 9.7 Implement perpetual restart recovery and ledger reconciliation before new entries; block all perpetual entries on unreconciled state. *(`PerpPaperAdapter.reconcile_open_positions`: every open position needs a fresh mark on restart; a missing/stale mark returns `reconciled=False` and records a `reconciliation_required` event per position.)*
- [x] 9.8 Produce a domain-separated perpetual report with price/funding/fee PnL, return on notional, maximum leverage, minimum liquidation distance, liquidation count, execution quality, data coverage, and promotion verdict.
- [x] 9.9 Add fixtures/tests for long/short PnL, funding sign, tick/minimum size, stale/one-sided quote, margin rejection, leverage cap, bracket failure, gap stress, liquidation, restart recovery, and no binary/perp ledger mixing. *(`tests/unit/test_perp_paper_safety.py`, 19 tests.)*
- [ ] 9.10 Complete BTC perpetual shadow validation and bracket/reconciliation drills before admitting any BTC perpetual paper fill; repeat independently for ETH, SOL, and XRP.

## 10. Sports feasibility closure and paper pilot

- [ ] 10.1 Complete the remaining `sports-evidence-and-flow-research` combined report task with sufficient causal sports captures; retain `insufficient_data` or `park` honestly if its threshold is not met. (Current capture status has 41,246 discovery rows but zero sports candles, so no report is honestly runnable yet.)
- [ ] 10.2 Select a proposed pre-game, single-game, two-outcome sports pilot only after provider coverage, entitlement, pricing, retention, attribution, rate-limit, and historical-snapshot requirements are reviewed and recorded.
- [x] 10.3 Implement the approved sports external-provider adapter with allowlist, raw provenance, event/market mapping, causal timestamps, parse/version status, conflicts, and gap reporting. *(`data/sports/provider_adapter.py`: `ProviderEntitlement`/`MarketMapping`/`ProviderRow`, `normalize_observation` (status = parsed/parse_error/unmapped/disallowed_source/stale), `detect_conflicts` with pre-registered resolution priority, `build_gap_report` that reports missing intervals without filling. No concrete provider is selected — that is 10.2.)*
- [x] 10.4 Add sports paper-admission checks requiring an exact matching `research_promising` report, market rules/official settlement, freshness, liquidity, strategy/model version, provider evidence, and sports risk policy.
- [x] 10.5 Implement the narrow sports binary paper adapter by reusing only safe binary fill/settlement mechanics after sports-specific admission; reject in-play, futures, props, parlays, combos, unclassified markets, stale evidence, and any copy-trade instruction. *(`execution/sports_paper.py::SportsPaperAdapter` wraps `PaperBroker` behind the orchestrator envelope; admission wall → in-play/event-started → `classify_market` (binary-only) → freshness → causal + non-conflicted evidence → `copy_trading_unsupported` → marketable-limit fill.)*
- [x] 10.6 Implement sports restart reconciliation and paper reports that preserve quote/evidence/model/risk lineage and official Kalshi resolution. *(`SportsPaperAdapter.reconcile` settles resolved open positions from the official Kalshi result only and blocks new entries while any position is unresolved; every decision payload carries candidate/report/settlement-source/quote lineage.)*
- [x] 10.7 Add tests for report prerequisites, changed candidate invalidation, provider conflicts, post-cutoff evidence, in-play rejection, insufficient liquidity, no fillable quote, official settlement, restart recovery, and `copy_trading_unsupported`. *(`tests/unit/test_sports_paper_pilot.py`, 21 tests.)*
- [ ] 10.8 Run a bounded sports shadow period; compare realized observable fill conditions to feasibility assumptions before any small-budget sports paper admission.

## 11. Cross-domain risk governance

- [x] 11.1 Define a versioned risk-policy model with global, domain, asset, `major-crypto` correlation-group, market/series, drawdown, daily-loss, consecutive-loss, freshness, and reconciliation limits.
- [x] 11.2 Implement risk admission that evaluates open positions/reserved exposure, worst-case binary loss, perpetual margin/liquidation/funding stress, and pending reconciliation against every applicable budget.
- [x] 11.3 Integrate quote/mark/funding/evidence/discovery/source-alignment freshness as fail-closed risk controls with durable block reasons.
- [x] 11.4 Route operator requests, drawdown/daily/consecutive loss, data integrity faults, process signals, margin breach/liquidation, and reconciliation faults through one durable global emergency-control state. *(`risk/governance.py::GlobalEmergencyControl` + `EmergencyHaltRecord` table (schema v10): all nine `HALT_SOURCES` write one append-only ledger; `blocks_entry()` is read fresh from the latest row so every domain sees the same halt; a second trigger during a halt keeps the first `halt_id`/reason.)*
- [x] 11.5 Implement audited resume requiring explicit operator action plus fresh health/reconciliation; process restart must not clear a halt. *(`GlobalEmergencyControl.resume` needs a non-empty operator id and a `HealthCheck(healthy=True)` callback; an unresolved condition raises `ResumeRefusedError` and lists it; a fresh control on a new session over the same DB still returns `blocks_entry()==True` — there is no auto-resume path.)*
- [x] 11.6 Implement per-scope promotion/demotion records and triggers for poor coverage, paper/backtest divergence, liquidity deterioration, integrity failure, or halted risk state; do not include a live lifecycle transition. *(`risk/governance.py::LifecycleGovernor` + `LifecycleTransitionRecord` table: promotion advances one ladder step, requires frozen `report_id`/manifest/model/risk-policy fingerprints and all `PROMOTION_GATES` passing; `DEMOTION_TRIGGERS` move one `ASSET:domain:candidate` scope to `blocked` without touching siblings; `validate_lifecycle` rejects any `live` target.)*
- [x] 11.7 Add tests for correlated simultaneous crypto signals, domain/asset/group/portfolio budget exhaustion, global-halt precedence, stale required data, liquidation halt, resume refusal, and isolated demotion. *(`tests/unit/test_risk_governance.py`, 26 tests: every trigger source, cross-domain block, global-halt-over-available-budget precedence, second-trigger idempotency, liquidation halt, resume refusal (no operator / unreconciled), restart persistence, promotion stage/fingerprint/gate enforcement, no-live target, isolated demotion, blocked-needs-review. Correlation-group/portfolio budget exhaustion is covered by `test_paper_policy.py`.)*

## 12. Website, operations, verification, and readiness

- [x] 12.1 Update the dashboard into all-domain overview plus Prediction Markets, Perpetuals, and Sports areas with BTC/ETH/SOL/XRP coverage, active/archived state, provenance/manifest, freshness, eligibility, candidate/gate status, risk, positions, and blockers. *(All-domain `paper_runs_overview` panel on `/`; each area page (`market_area.html`) now renders per-asset admission (BTC/ETH/SOL/XRP, eligible only when fresh+aligned+verified) and domain-scoped paper/shadow run health with reconciliation blockers, via `queries.domain_paper_runs` + `queries.asset_admissions`.)*
- [x] 12.2 Add dashboard/query tests proving stale, unavailable, unverified, or source-misaligned data cannot render as eligible and sports remains visibly disabled until its report passes. *(`asset_admissions` now gates `eligible` on `verified and fresh(<=DISCOVERY_FRESH_MAX_AGE_S) and source_aligned`; `tests/unit/test_asset_admissions.py` (5) + `tests/unit/test_dashboard_paper_runs.py` (5) cover stale/misaligned/unverified/undiscovered → not eligible, and sports contributing no eligible rows and rendering `research`/`discovered` only.)*
- [x] 12.3 Implement foreground operator commands for discovery, import/validate, manifest creation, backtest, shadow, paper run, report/health, reconciliation, halt, and resume, with non-secret effective-config audit records. *(`execution/operator_cli.py::OperatorConsole` + `scripts/operate.py`: shell sub-commands wrap the bounded scripts; `health`/`reconcile` read `build_run_health_report`; `halt`/`resume` drive `GlobalEmergencyControl` (resume refuses without an operator). Every invocation writes a `redact_export`-scrubbed effective-config `PaperAuditEvent` (`kind="operator_command"`) under a per-UTC-day `ops` run.)*
- [x] 12.4 Implement run-health and reconciliation reports that distinguish no signal, policy block, stale data, missing coverage, execution rejection, and system failure; include domain-separated ledgers and backtest-divergence metrics. *(`execution/run_reporting.py`: `classify_status` maps every adapter decision status to one of the six outcomes (unknown → `policy_block`, never a healthy hold); `build_run_health_report` builds per-domain `DomainLedger`s that never merge, latest-wins reconciliation status with `blocks_new_entries`, and a `DivergenceMetric` block vs. a frozen backtest summary. `tests/unit/test_run_reporting.py`, 8 tests.)*
- [x] 12.5 Ensure all exports omit secrets and preserve source attribution/retention constraints; test report serialization and redaction.
- [x] 12.6 Document setup, local data storage, Binance/Coinbase/TradingView roles, Kalshi demo requirement, asset-lifecycle review, source-alignment review, shadow-to-paper promotion, emergency halt, reconciliation, demotion, and rollback procedures.
- [ ] 12.7 Run lint, type checks, schema migration tests, unit tests, deterministic source/backtest fixtures, and controlled demo-environment integration tests; record versions and any skipped tests. (933 unit tests pass and Ruff passes; full Pyright still reports 72 pre-existing typing errors, and 3 external integration tests remain deselected.)
- [ ] 12.8 Run and archive first baseline reports for BTC, ETH, SOL, and XRP separately; no report may be marked a promotion pass without its frozen evidence, coverage, and component gates.
- [ ] 12.9 Conduct operator dry-runs for each domain: safe-start refusal, normal interrupt, emergency halt, restart reconciliation, stale-data failure, and dashboard visibility; record outcomes.
- [ ] 12.10 Admit only the first asset/domain pair that passes all prerequisite gates to a bounded paper run; keep every other pair in its earned lifecycle state and publish a readiness matrix.
