# Design: core-data-and-backtesting

## Context

Greenfield rebuild of a Kalshi trading bot whose v1 failed for structural reasons: no backtesting (strategies validated only by risking money forward), a 3,771-line orchestration monolith, config drift between docs and code, and near-zero test coverage. The full architecture plan lives at the repo owner's plan file and is summarized in `README.md`; this change implements its Phase 1. Constraints: solo developer, Windows 11 local machine now / home server later, Python 3.12 via uv, $0 budget for data (Kalshi's official historical candlestick endpoint is free and unauthenticated for public data).

## Goals / Non-Goals

**Goals**
- Backtest any `StrategyProtocol` implementation against real Kalshi history with zero credentials
- The strategy/risk code path exercised by the backtester is byte-identical to what paper/live modes will use later — only the injected `BrokerAdapter` and data source differ
- Metrics output makes fee-adjusted reality unmissable (breakeven win rate displayed next to achieved win rate)
- Known-answer tests for every piece of financial math before it influences any decision

**Non-Goals**
- No live or paper order placement (later changes)
- No WebSocket streaming (paper-trading change)
- No Webull, no weather/econ strategies, no AI/ML signals (later changes; the `StrategyProtocol` must not preclude them)
- No order-book-level backtest fidelity (candlestick bars only; third-party order-book replay data is a later, if-proven-necessary addition)

## Decisions

1. **Event-driven bar replay, not vectorized backtesting.** A vectorized backtester (pandas-wide operations) is faster but forces strategy logic to be written twice — once vectorized for backtest, once event-wise for live. v1 died from exactly this kind of duplication pressure. The engine steps bar-by-bar, building a `StrategyContext` and calling `strategy.evaluate(context)` exactly as the live loop will. Slower, but correctness-preserving; speed is irrelevant at this data scale (minutes-level bars, handful of series).

2. **`BrokerAdapter` as a `typing.Protocol`, introduced now with one implementation.** The protocol ships in this change with only `BacktestBroker` implementing it, so the strategy/risk layers are written against the abstraction from day one rather than retrofitted. Alternative — introduce the protocol when the second broker arrives — rejected because retrofitting is how v1's paper/live split ended up as two near-duplicate 1,000-line files.

3. **SQLite via SQLAlchemy 2.0, single schema-of-record.** Candles, signals (every evaluation, not just trades — v1's audit-trail pattern, kept), simulated trades, and backtest runs all in one schema. Postgres portability preserved by avoiding SQLite-only column types. Alternative — parquet files for candles — rejected for now: one storage system is simpler, and the data volume is tiny.

4. **Fill simulation is pessimistic by default.** Backtest fills execute at the bar's worst plausible price for the order side (configurable to midpoint for sensitivity analysis), and Kalshi's 7% fee on net winnings is applied in the fill model itself, not as a reporting adjustment. Optimistic fill assumptions are the classic way backtests lie; v1's failure mode (edge that evaporates after fees) must be unrepresentable here.

5. **Volatility estimation ports v1's fallback chain** (30-day historical → EWMA → intraday) with tests, sourced from Coinbase/Kraken daily klines fetched by `scripts/fetch_historical.py` — CF Benchmarks constituent exchanges, matching Kalshi settlement (v1's correct choice, preserved).

6. **Out-of-sample discipline is engine-enforced.** `BacktestEngine.run()` takes an explicit `train/test` date split; metrics are reported per segment and the go/no-go evaluation only reads the test segment. Leaving this to operator discipline is how overfitting sneaks in.

## Risks / Trade-offs

- [Kalshi candlestick coverage for older/settled markets may be sparse or short-history] → verify data availability for target series (KXBTC, KXBTCD, KXETH, KXETHD) as the first implementation task, before building the engine around assumptions; fall back to third-party archives only if official data is genuinely insufficient
- [Candle-level replay can't model spread/queue effects, overstating fillability] → pessimistic fill model (Decision 4); order-book replay explicitly deferred, not forgotten
- [Porting v1 math risks porting v1 bugs] → every ported function gets known-answer tests against independent references (analytic digital-option values, scipy-computed baselines) before integration
- [Backtest engine itself could have a bug producing falsely-good metrics] → synthetic-data known-answer tests: hand-constructed price paths where the correct trades and final PnL are computable by hand; the engine must reproduce them exactly

## Migration Plan

Greenfield — nothing to migrate. Rollback = revert commits; no data or config migrations involved.

## Open Questions

- Exact numeric go/no-go thresholds (Sharpe > 1.0 is proposed, not calibrated) — finalize after first real backtest output exists, recorded as a spec amendment
- Which crypto series have deep-enough candlestick history to make the out-of-sample split meaningful — answered by the first implementation task
