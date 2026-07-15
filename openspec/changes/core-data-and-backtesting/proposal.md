# Proposal: core-data-and-backtesting

## Why

v1 of this bot went live on an unvalidated strategy (~50-51% win rate — a net loser after Kalshi's 7% fee on winnings) because there was no way to test a hypothesis other than risking money forward in real time. This change builds the foundation that makes cheap, honest validation possible: Kalshi historical data ingestion, the pricing/signal math, the crypto mispricing strategy, and an event-driven backtesting engine that runs the exact same strategy and risk code that will later run live. **No live-order code is in scope** — the only broker exercised is a simulated `BacktestBroker`.

## What Changes

- New `storage/` package: SQLAlchemy models + session factory — single schema of record (markets, candles, signals, simulated trades, backtest runs)
- New `data/kalshi/` package: unauthenticated REST client for public market data + the historical candlestick endpoint (1min/60min/1440min), with a bulk-fetch script for seeding backtest datasets
- New `signals/` package: Black-Scholes digital-option fair value (`N(d2)`, successor to v1's verified-correct implementation), Monte Carlo cross-check (Student-t fat-tail shocks), and volatility estimators
- New `strategy/` package: `StrategyProtocol` (`evaluate(context) -> Decision`) + `crypto_mispricing.py` — generalized successor to v1's `aggregator.py`, fee-aware edge calculation preserved
- New `risk/` package (sizing math only, no live wiring): fractional-Kelly position sizer with the 5% hard cap, drawdown guard state machine
- New `execution/broker_protocol.py` + `backtest_broker.py`: the `BrokerAdapter` protocol and its first (simulated) implementation
- New `backtest/` package: event-driven replay engine + metrics (fee-adjusted win rate shown against fee-adjusted breakeven, Sharpe/Sortino, max drawdown, PnL per asset/cadence)
- Test coverage: known-answer tests for all signal math, Kelly/drawdown edge cases, and backtest-engine correctness via synthetic-data replay with hand-computed expected results

## Capabilities

### New Capabilities

- `kalshi-market-data`: fetching, storing, and replaying Kalshi public market data and historical candlesticks without credentials
- `pricing-signals`: fair-value pricing of binary contracts (Black-Scholes digital, Monte Carlo cross-check) and volatility estimation
- `crypto-mispricing-strategy`: composite edge-vs-market-price decision logic for Kalshi crypto threshold/range contracts, fee-aware
- `risk-sizing`: fractional-Kelly position sizing with hard caps and drawdown-guard state transitions
- `backtest-engine`: event-driven historical replay producing go/no-go metrics, running identical strategy/risk code as future live mode

### Modified Capabilities

(none — greenfield)

## Impact

- New packages under `src/kalshi_bot/`: `storage/`, `data/`, `signals/`, `strategy/`, `risk/`, `execution/`, `backtest/`
- New dependencies: none beyond what `pyproject.toml` already declares (httpx, sqlalchemy, numpy, scipy, pandas)
- New script: `scripts/fetch_historical.py`
- Reference material (read-only): `../Kalshi-Trading-Bot-OLD/src/signals/{black_scholes,monte_carlo,aggregator}.py`, `src/risk/kelly.py` — verified-correct math to port with tests, not copy blindly
- Gate created by this change: backtest metrics must clear the phase bar (out-of-sample Sharpe > 1.0 proposed, fee-adjusted win rate meaningfully above breakeven, drawdown within guard tolerance) before the `paper-trading-and-notify` change may begin
