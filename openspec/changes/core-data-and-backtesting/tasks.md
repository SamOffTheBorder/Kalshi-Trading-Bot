# Tasks: core-data-and-backtesting

## 1. Storage foundation

- [x] 1.1 `storage/models.py`: SQLAlchemy 2.0 models — `Candle`, `SignalRecord`, `SimulatedTrade`, `BacktestRun` (single schema of record; no SQLite-only column types) — plus `SpotCandle` for task 2.5's klines
- [x] 1.2 `storage/db.py`: engine/session factory reading `Settings.db_path`
- [x] 1.3 Unit tests: model round-trips, candle unique-constraint dedup

## 2. Kalshi market data (verify availability FIRST)

- [x] 2.1 `data/kalshi/client.py`: unauthenticated httpx client — markets, events, series, historical candlesticks; client-side rate limiter (≤20 req/s), exponential backoff on 429/5xx, fail-fast on 401/403
- [x] 2.2 **Spike: fetch real candlestick coverage for KXBTC, KXBTCD, KXETH, KXETHD** — findings in `notes.md`: ~6-week rolling retention (earliest ~2026-06-01), dollar-string payload format, sparse 1-min candles → archive continuously, 60-min primary
- [x] 2.3 `data/kalshi/coverage.py`: per-series coverage report (first/last candle, gaps)
- [x] 2.4 `scripts/fetch_historical.py`: bulk pull into storage, idempotent re-runs (resume via already-candled ticker skip)
- [x] 2.5 Crypto spot history for volatility: Coinbase/Kraken daily klines fetch (CF Benchmarks constituents)
- [x] 2.6 Unit tests with recorded/mocked responses; integration-marked test hitting the real public endpoint

## 3. Pricing signals (known-answer tests before integration)

- [ ] 3.1 `signals/black_scholes.py`: N(d2) digital fair value + range/bucket via digital difference — port from v1 with tests against analytic values (1e-9 tolerance)
- [ ] 3.2 `signals/monte_carlo.py`: Student-t GBM paths, probability estimate + BS/MC divergence measure; test convergence to BS under near-normal df
- [ ] 3.3 `signals/volatility.py`: 30d-historical → EWMA → intraday fallback chain, labeled source; tests for each fallback trigger

## 4. Strategy layer

- [ ] 4.1 `strategy/base.py`: `StrategyProtocol`, `StrategyContext`, `Decision` types — zero imports from data/execution modules
- [ ] 4.2 `strategy/crypto_mispricing.py`: fee-adjusted edge (7% on net winnings, subtracted before gates), BS/MC divergence guard, min-edge threshold from Settings
- [ ] 4.3 Persist every Decision (including HOLD + reason) via storage
- [ ] 4.4 Unit tests: fee flips marginal edge to HOLD; divergence blocks entry; edge math against hand-computed cases

## 5. Risk sizing

- [ ] 5.1 `risk/kelly.py`: binary fractional Kelly, `min()` clamp at `max_position_pct` — port v1 math with edge-case tests (zero/negative edge, cap exceeded, near-zero bankroll)
- [ ] 5.2 `risk/drawdown_guard.py`: NORMAL/PAUSED/HALTED state machine, thresholds only from Settings; state-transition boundary tests

## 6. Broker protocol + backtest broker

- [ ] 6.1 `execution/broker_protocol.py`: `BrokerAdapter` Protocol + `OrderRequest`/`OrderResult`/`Position`/`MarketSnapshot` pydantic models
- [ ] 6.2 `execution/backtest_broker.py`: pessimistic fills (worst plausible bar price for side; midpoint mode for sensitivity), 7% fee inside settlement model
- [ ] 6.3 Unit tests: fill pricing per side, fee-at-settlement correctness

## 7. Backtest engine

- [ ] 7.1 `backtest/engine.py`: bar-by-bar replay building `StrategyContext`, calling strategy → risk sizing → broker; enforced train/test split parameter
- [ ] 7.2 `backtest/metrics.py`: win rate + fee-adjusted breakeven side-by-side, Sharpe, Sortino, max drawdown, PnL per asset/cadence — per segment
- [ ] 7.3 Known-answer replay tests: synthetic paths + deterministic strategy → exact expected trade list and PnL
- [ ] 7.4 `BacktestRun` persistence: parameters, data range, metrics stored per run

## 8. First real backtest + gate review

- [ ] 8.1 Run crypto mispricing strategy over full available history with train/test split
- [ ] 8.2 Record results in the change; propose calibrated go/no-go thresholds (replacing the placeholder Sharpe > 1.0) as a spec amendment
- [ ] 8.3 Docs: architecture + runbook pages in docs-site for fetching data and running a backtest
