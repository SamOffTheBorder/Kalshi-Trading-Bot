# System overview

A multi-market trading bot: **Kalshi event contracts** (crypto now; weather and economic
indicators later) plus **Webull defined-risk options** (later phase). Rebuilt from a v1
whose core failure was going live on an unvalidated edge — ~50-51% win rate, a net loser
after Kalshi's 7% fee — because it had no way to test hypotheses other than risking money.

## Structural rules

1. **Backtest-first.** No strategy touches paper trading until it clears a fee-adjusted
   bar on *out-of-sample* history; no strategy touches live money until it also
   forward-validates in paper mode. The train/test split is enforced by the engine.
2. **One decision path.** `strategy/` and `risk/` code is broker- and mode-agnostic; the
   backtest engine, paper loop, and live loop inject different `BrokerAdapter`
   implementations into the same code. There is no second copy of the logic to drift.
3. **Fees inside the model.** Kalshi's 7% fee on net winnings is subtracted before every
   edge gate and applied inside fill/settlement simulation — never a reporting adjustment.
4. **Config has one home.** Every tunable lives in `config/settings.py`; `.env.example`
   is generated from it, and drift fails CI.
5. **Every evaluation is audited.** All decisions — including HOLDs, with reasons — persist
   to the `signals` table.

## Modules (`src/kalshi_bot/`)

| Module | Role |
|---|---|
| `config/` | `Settings` — the single source of truth |
| `storage/` | SQLAlchemy schema of record (candles, markets, signals, trades, runs) |
| `data/` | Kalshi public client + parser, spot klines (Coinbase/Kraken — CF Benchmarks constituents, matching Kalshi settlement) |
| `signals/` | Pure pricing math: Black-Scholes digital N(d2), Student-t Monte Carlo, volatility fallback chain |
| `strategy/` | `StrategyProtocol` + crypto mispricing strategy (fee-adjusted EV, divergence guard) |
| `risk/` | Fee-aware fractional Kelly with 5% hard cap, drawdown guard state machine |
| `execution/` | `BrokerAdapter` protocol; `BacktestBroker` (pessimistic fills) today, Kalshi/paper/Webull adapters in later changes |
| `backtest/` | Event-driven replay engine + fee-honest metrics |

## Key data facts (verified against the live API)

- Kalshi's public API retains settled markets for only **~6 weeks** — the local DB is the
  real archive and must be refreshed regularly.
- Hourly markets get exactly one 60-minute candle, timestamped at market close —
  backtesting them requires **1-minute candles**.
- Prices arrive as decimal-dollar strings (`"0.4500"`), volume as `volume_fp` strings;
  `data/kalshi/parse.py` is the single home for that format knowledge.

## Change workflow

Work is planned and tracked with [OpenSpec](https://openspec.dev/) under `openspec/`.
Sequence: `core-data-and-backtesting` → `paper-trading-and-notify` →
`dashboard-and-live-gate` → Webull options → AI/ML layer + weather/econ strategies.
Each phase transition has explicit go/no-go criteria.
