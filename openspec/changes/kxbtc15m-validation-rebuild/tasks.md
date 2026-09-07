## 1. Evidence Baseline and Data Contract

- [x] 1.1 Mark existing v2 reports as diagnostic only and add a KXBTC15M-only run configuration with dataset provenance. Added evidence classification/provenance columns and `--kxbtc15m-only`; fingerprints include rows, range, config versions, and git context. 2 new tests; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.2 Audit Kalshi fixed-point field handling and migrate persisted prices and quantities to retain exchange precision without rewriting historical rows. Parser now uses Decimal for legacy cents and retains exact nullable `*_dollars`/`*_fp` values; versioned additive migration covers populated and fresh SQLite. 2 migration/precision tests; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.3 Define timestamp/availability metadata for Kalshi market, order-book, public-trade, BRTI, and candle observations. Added `observed_at`/`available_at` plus capture provenance and documented canonical names for all five observation types. 1 schema test; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.4 Implement deliberate-session capture and import paths for the required KXBTC15M, BRTI, L2, and trade data, including gap/provenance reporting. Added foreground-only `scripts/capture_session.py`, conservative 8/s Kalshi capture, timestamped JSONL imports, session tagging, and per-kind gap/session reports. 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.5 Version the market-resolution and fee configuration used by each validation run and add tests against documented fee and resolution examples. Added versioned `FeeConfig`/`ResolutionSpec`, run columns, and hand-worked 42c × 11 taker fee plus tie/direction resolution tests. 2 example tests; 338 non-backtest tests passed; ruff + pyright clean.

## 2. Causal Backtest and Execution Accounting

- [ ] 2.1 Refactor the backtest timeline so features use only as-of observations and orders execute only on later eligible events.
- [ ] 2.2 Restrict bar-only datasets to next-bar-or-later execution and add regression tests that detect look-ahead through incomplete OHLC bars.
- [x] 2.3 Correct directional decision contracts so BUY YES and BUY NO both carry a valid, side-consistent fair probability and no default certainty path exists.
- [x] 2.4 Rebuild simulated YES/NO lifecycle accounting with explicit entry/exit cashflows, fees on each matched leg, fractional quantity support, and side-aware early exits.
- [x] 2.5 Implement taker-only executable pricing as the initial execution model; record resting orders as unfilled until a validated queue/partial-fill model is introduced.
- [ ] 2.6 Add unit and scenario tests for NO-side gains, early-close double-leg fees, unfilled maker orders, timestamp causality, and precision retention.

## 3. Risk, Walk-Forward, and Reporting Gates

- [ ] 3.1 Make fixed dollar risk derive from executable stop distance and full expected costs; remove baseline Kelly sizing from the validation path.
- [ ] 3.2 Compute per-trade breakeven and expectancy from actual entry, stop, target, fill assumptions, and both-leg costs.
- [ ] 3.3 Implement embargoed rolling walk-forward evaluation with fresh broker, cash, and risk-guard state for every out-of-sample fold.
- [ ] 3.4 Produce per-fold and aggregate reports for net expectancy, coverage, calibration/Brier score, realized versus modeled costs, fills, cancels, partial fills, and adverse selection.
- [ ] 3.5 Add day-blocked bootstrap confidence intervals and parameter-stability/latency-outage sensitivity checks to the promotion report.
- [ ] 3.6 Define and enforce the paper-trading promotion gate; preserve failed and legacy results without treating them as passing evidence.

## 4. Settlement-Aware and Trend Research

- [ ] 4.1 Implement KXBTC15M target and settlement-window feature construction from timestamped BRTI observations and time remaining.
- [ ] 4.2 Build a train-fold-only calibrated probability baseline and persist model/version/input metadata with each estimate.
- [ ] 4.3 Compare calibrated fair probability with side-specific executable prices and full expected friction before emitting a trade candidate.
- [ ] 4.4 Reimplement trend and pullback features on short-horizon BRTI/perpetual data, and report their incremental out-of-sample value against the settlement-aware baseline.
- [ ] 4.5 Add separately labeled experiments for microprice, public-trade imbalance, and quarter-hour opening effects; defer each when the required data coverage is insufficient.
- [ ] 4.6 Run reproducible KXBTC15M-only validation and document whether any candidate satisfies the promotion gate.

## 5. Perpetual Isolation and Execution Safety

- [ ] 5.1 Split perp strategy ledger, metrics, and promotion configuration from binary-event strategy reporting.
- [ ] 5.2 Disable market-neutral funding-carry classification unless a compatible linear hedge, rebalance cadence, complete fees, funding, and residual risk are modeled.
- [ ] 5.3 Implement idempotent order tracking, restart reconciliation, partial-fill handling, and stale-order cancellation for paper/perp execution.
- [ ] 5.4 Use anchored reduce-only exit triggers where supported and verify emergency-close fills before declaring a position closed.
- [ ] 5.5 Add failure-mode tests for restart with open orders, partial fills, unconfirmed emergency exits, and an unsupported binary hedge.

## 6. Operator Surface and Verification

- [ ] 6.1 Update the dashboard and run artifacts to show instrument scope, data freshness/provenance, model/calibration version, promotion status, and unresolved execution state.
- [ ] 6.2 Update strategy research and operator documentation to distinguish validated evidence, experiments, deferred data-dependent work, and disabled perp carry.
- [ ] 6.3 Run unit, integration, causal-regression, and walk-forward reproducibility tests; record the exact data/configuration versions used.
- [ ] 6.4 Validate paper-mode restart, reconciliation, anchored exits, stale-order handling, and kill-close confirmation before enabling any paper strategy.
