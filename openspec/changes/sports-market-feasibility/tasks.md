## 1. Research data foundation

- [x] 1.1 Add additive sports-series, market-rule-provenance, and point-in-time observation records; include migrations and indexes needed for chronological market queries.
- [x] 1.2 Add a sports market classifier that recognizes supported two-outcome single-game contracts and returns explicit rejection reasons for futures, props, combos, multi-outcome markets, unknown rules, and invalid metadata.
- [x] 1.3 Add public Kalshi sports discovery that persists series/market metadata, settlement sources, fee metadata, liveness, spread, open interest, volume, and available depth.
- [x] 1.4 Add known-answer and fixture tests for eligible markets, each rejection path, changing-rule provenance, and high-volume but untradeable markets.

## 2. Foreground sports capture

- [x] 2.1 Implement foreground, read-only capture of supported sports market candles, order books, and public trades with observed/available timestamps and capture-session provenance.
- [x] 2.2 Implement per-market gap detection and capture reporting without interpolation or synthetic fills.
- [x] 2.3 Add an operator-run command for discovery, bounded capture, and coverage reporting; it must not schedule, restart, or place orders.
- [x] 2.4 Add tests proving timestamp causality, restart-visible gaps, no unattended behavior, and market terms joinability.

## 3. Execution-realistic feasibility evaluation

- [x] 3.1 Define the sports market baseline and candidate-signal interfaces, including time-to-event bucketing and point-in-time feature contracts.
- [x] 3.2 Implement chronological train/holdout evaluation with fit-on-prior-data-only calibration and a holdout-contamination guard.
- [x] 3.3 Implement sports fill simulation using actual quotes or resting-fill conditions, market-specific fees, spread, slippage, available depth, and partial/rejected fills.
- [x] 3.4 Implement a feasibility report with market-baseline comparison, calibration/probabilistic metrics, fee-adjusted PnL, executable-size statistics, concentration, drawdown, and explicit research outcome.
- [x] 3.5 Add known-answer and integration tests for fill rejection, fee erosion, partial depth, time-to-event segmentation, insufficient data, and a candidate that is accurate but fails calibration.

## 4. External-data boundary and research gate

- [x] 4.1 Define an opt-in external sports-source adapter contract that requires provider, endpoint, observed time, available time, and provenance; do not select or add a provider.
- [x] 4.2 Document the sports feasibility operator runbook, including supported market shape, manual capture cadence, rule review, and the prohibition on paper/live orders.
- [ ] 4.3 Pre-register the first pilot's sport/series, discovery thresholds, holdout boundary, fee/slippage assumptions, and minimum sample/confidence gates before examining its holdout.
- [ ] 4.4 Run the first complete feasibility report after sufficient foreground data is captured; record `research_promising`, `park`, or `insufficient_data` without enabling execution. (Blocked by current zero-row `sports_candles` capture; discovery alone is not sufficient evidence.)
