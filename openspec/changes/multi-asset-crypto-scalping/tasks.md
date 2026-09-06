> **Dependency:** Sections 3–5 build on `kxbtc15m-validation-rebuild`'s
> causal simulation path (`causal-strategy-validation`), settlement-aware
> pricing, and `perps-strategy-isolation` gate. Land that change's engine,
> side-aware accounting, and per-fold isolation work first; the tasks below add
> the registry and per-asset budgeting on top of it, not a parallel execution
> model. Sections 1–2 (registry, discovery, collection, persistence) have no
> such dependency and can proceed immediately.

## 1. Registry and configuration foundation

- [ ] 1.1 Add typed `CryptoAssetConfig` and `CryptoInstrumentConfig` models with stable asset IDs, per-cadence (`15m`/`60m`) event-series metadata and contract shape, lifecycle mode, approved spot-feed mappings, optional perp metadata, and correlation group.
- [ ] 1.2 Populate the shipped registry: preserve BTC; configure ETH as `backtest` for 15-minute and hourly markets; configure SOL, XRP, DOGE, BNB, HYPE, NEAR, and ZEC as `observe` for every listed cadence; add LINK only as an observation/perp candidate until a compatible event series is verified.
- [ ] 1.3 Add settings validation that rejects duplicate asset IDs/series, an unsupported lifecycle mode, absent spot mapping for a spot-dependent asset, and missing correlation groups.
- [ ] 1.4 Add generated `.env.example` coverage and unit tests for registry/settings validation without exposing secrets.
- [ ] 1.5 Replace BTC-specific public constants at application boundaries with registry lookups while retaining backwards-compatible BTC defaults where external scripts require them.

## 2. Market discovery, data collection, and persistence

- [ ] 2.1 Add an explicit public event-series discovery service that validates each configured 15-minute and hourly series, captures active market shape/cadence and quote metadata, and persists an asset/instrument/cadence discovery snapshot with timestamp and failure reason.
- [ ] 2.2 Add authenticated margin-market discovery for optional perps, recording contract multiplier, minimum order size, leverage, funding availability, and reference-index metadata separately from event discovery.
- [ ] 2.3 Define and implement the event/perp compatibility check: same registered asset, active instruments, compatible index/settlement metadata, current contract metadata, and a bounded snapshot age.
- [ ] 2.4 Add an idempotent schema migration mechanism and additive persistence for registry snapshots, discovery/eligibility results, and asset-attributed run/admission records; test populated SQLite upgrade and fresh database creation.
- [ ] 2.5 Generalize `fetch_historical.py` to select registry assets in `observe` or higher mode, archive each validated 15-minute and hourly event series, fetch only approved asset spot feeds, and print per-asset/cadence results. Keep event cadence separate from candle period; hourly markets must retain fine-grained candles for simulation.
- [ ] 2.6 Generalize `archiver_loop.py` to use the registry while preserving its manual foreground-only policy, per-series time budget, resumable collection, and no scheduler/service behavior.
- [ ] 2.7 Implement asset-level coverage and market-liveness qualification using configurable spread, depth, OI, recent-volume, coverage, gap, and freshness thresholds; fail closed on unavailable data.
- [ ] 2.8 Add fixture-based tests for valid discovery, missing/renamed event series, malformed market shape, missing spot feed, stale snapshots, one-sided quotes, and incompatible event/perp pairs.

## 3. Backtesting and strategy evidence

- [ ] 3.1 Replace `BacktestEngine.SERIES_SYMBOL` with registry-backed market-to-asset resolution and skip/record unmapped markets without using another asset's spot history. Per-asset runs execute on `kxbtc15m-validation-rebuild`'s causal path (as-of timestamps, no incomplete-bar fills, fresh per-fold broker/guard state, side-aware YES/NO + both-leg fees); do not add an asset-specific execution path.
- [ ] 3.2 Add asset ID, event cadence, and immutable registry/configuration snapshot to backtest-run inputs, signal context, simulated-trade records, and serialized reports.
- [ ] 3.3 Compute and persist train/test metrics separately for every participating asset/cadence as well as aggregate portfolio metrics, including each asset/cadence's eligible window and data-quality summary.
- [ ] 3.4 Update `run_scalping_backtest.py` with explicit asset selection and an asset-aware data-range check; preserve a BTC-only default for reproducible existing runs.
- [ ] 3.5 Enforce asset-specific promotion evidence so pooled results cannot authorize an individual asset, and add report output that clearly flags an aggregate/asset disagreement.
- [ ] 3.6 Add known-answer and regression tests proving ETH uses ETH spot history for both cadences, BTC results remain unchanged under its default registry entry, unmapped markets are skipped, hourly candles are not look-ahead sampled at close, and an aggregate pass cannot override an asset/cadence failure.

## 4. Multi-asset portfolio risk and sizing

- [ ] 4.1 Add a portfolio admission component that evaluates global controls, crypto gross-risk budget, correlation-group budget, per-asset budget, and existing fixed-R/exchange constraints in the documented order.
- [ ] 4.2 Add configurable portfolio, group, per-asset, and maximum-open-asset-direction limits, with all initial crypto assets assigned to the conservative `major-crypto` group.
- [ ] 4.3 Integrate admission with fixed-risk sizing so candidate quantities are clamped down to a valid increment or fail closed when a minimum contract exceeds remaining budget.
- [ ] 4.4 Persist admission inputs, candidate/admitted quantity, group exposure, and a precise rejection/reduction reason for every decision that reaches risk admission.
- [ ] 4.5 Add unit and integration tests for simultaneous correlated signals, exhausted asset/group/portfolio budgets, unaffordable event/perp minimum sizes, daily halt precedence, and asset demotion while positions are open.

## 5. Perps and execution integration

- [ ] 5.1 Make event and margin execution adapters require registry authorization and a fresh eligible discovery snapshot before accepting a non-BTC entry.
- [ ] 5.2 Generalize contract sizing and exit-trigger construction to validated per-asset contract metadata while retaining the 2x default, 3x hard leverage ceiling, and immediate close on failed bracket attachment.
- [ ] 5.3 Gate `funding_carry` and all event/perp hedge construction on a fresh compatibility result AND `kxbtc15m-validation-rebuild`'s `perps-strategy-isolation` gate (demonstrated compatible linear hedge, rebalance cadence, full fees, residual basis risk); a binary event contract is never a linear hedge. Return an auditable HOLD reason for prediction-only, perp-only, stale, mismatched, or not-yet-gated assets.
- [ ] 5.4 Add fake-client tests for ETH perpetual sizing and bracket failure, metadata changes, prediction-only assets, LINK without an event hedge, and a verified compatible pair.
- [ ] 5.5 Paper-test ETH event execution only after its per-asset backtest gate passes; paper-test ETH perps and any hedge separately after the required bracket and compatibility checks pass.

## 6. Dashboard, documentation, and release gates

- [ ] 6.1 Replace BTC-specific dashboard queries/cache names and templates with registry-driven crypto asset/cadence coverage, discovery, lifecycle, and eligibility views for 15-minute and hourly markets.
- [ ] 6.2 Add dashboard panels for event/perp/pair compatibility, snapshot freshness, asset and correlation-group exposure, per-asset metrics, and the exact reason for blocked/reduced entries.
- [ ] 6.3 Ensure observation-only assets are visibly non-tradable and stale/unavailable data cannot render as eligible; add route/template tests for ETH, an observation asset, and a stale snapshot.
- [ ] 6.4 Update operational docs with the registry modes, manual collection commands, discovery/coverage review, ETH-first promotion procedure, demotion/rollback procedure, and the continuing prohibition on unattended processes.
- [ ] 6.5 Run formatting, the complete relevant test suite, schema-upgrade tests, and one manual discovery/coverage report; attach asset-level evidence before changing any lifecycle mode beyond its shipped default.
- [ ] 6.6 Require an explicit operator review of frozen per-asset OOS and paper results before each one-at-a-time promotion; no asset reaches live mode under this change without the existing v2 live gates as well.
