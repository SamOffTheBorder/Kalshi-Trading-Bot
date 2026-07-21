---
sidebar_position: 1
---

# System overview

A multi-market trading bot: **Kalshi event contracts** — crypto and weather actively
backtested today, economic indicators planned — with Webull defined-risk options
deferred indefinitely (see [Project scope](../project-scope.md)). Rebuilt from a v1 whose
core failure was going live on an unvalidated edge — ~50-51% win rate, a net loser after
Kalshi's 7% fee — because it had no way to test hypotheses other than risking money.

## Structural rules

1. **Backtest-first.** No strategy touches paper trading until it clears a fee-adjusted
   bar on *out-of-sample* history; no strategy touches live money until it also
   forward-validates in paper mode. The train/test split is enforced by the engine
   (`start_ts < split_ts < end_ts` is a hard precondition, not a convention).
2. **One decision path.** `strategy/` and `risk/` code is broker- and mode-agnostic; the
   backtest engine, paper loop, and live loop inject different `BrokerAdapter`
   implementations into the same code. There is no second copy of the logic to drift.
3. **Fees inside the model.** Kalshi's 7% fee on net winnings is subtracted before every
   edge gate and applied inside fill/settlement simulation — never a reporting adjustment.
4. **Fills are pessimistic by default.** Buying YES pays the bar's *highest* ask; buying
   NO pays 100 minus the *lowest* bid. Fills are additionally capped at a fraction of the
   bar's actual traded volume (`liquidity_cap_frac`, default 25%) — added after an early
   backtest compounded a position past a market's entire *lifetime* volume and produced
   fantasy PnL. The rule this project holds itself to: tighten realism to find out if an
   edge survives it; never loosen it to manufacture a pass.
5. **Config has one home.** Every tunable lives in `config/settings.py`; `.env.example`
   is generated from it, and drift fails CI.
6. **Every evaluation is audited.** All decisions — including HOLDs, with reasons —
   persist to the `signals` table.

## Modules (`src/kalshi_bot/`)

| Module | Role |
|---|---|
| `config/` | `Settings` — the single source of truth |
| `storage/` | SQLAlchemy schema of record (candles, markets, signals, trades, runs) |
| `data/` | Kalshi public client + parser, spot klines (Coinbase/Kraken — CF Benchmarks constituents, matching Kalshi settlement) |
| `signals/` | Pure pricing math: Black-Scholes digital N(d2), Student-t Monte Carlo, volatility fallback chain |
| `strategy/` | `StrategyProtocol` + crypto mispricing strategy (fee-adjusted EV, divergence guard, trend-regime gate) |
| `risk/` | Fee-aware fractional Kelly with hard cap, drawdown guard state machine, per-series entry throttle |
| `execution/` | `BrokerAdapter` protocol; `BacktestBroker` (pessimistic, liquidity-capped fills) today, Kalshi/paper adapters in later changes |
| `backtest/` | Event-driven replay engine + fee-honest metrics |

## Risk management

Three mechanisms sit between a strategy's decision and a filled order, each added or
fixed in direct response to something a real backtest run exposed:

- **Fractional Kelly + hard cap** (`risk/kelly.py`) — quarter-Kelly by default, clamped
  by `min()` to a hard percentage of bankroll regardless of what Kelly's formula alone
  would size.
- **Entry throttle** (`risk/entry_throttle.py`) — caps filled entries per series within a
  rolling window (default 3 per 24h). Added after an early run showed all 23 trades in a
  67-day backtest firing inside one 15-hour trending episode — a single bad cluster was
  dominating the whole result. Per-trade caps don't bound an *episode*; this does.
- **Drawdown guard** (`risk/drawdown_guard.py`) — a NORMAL → PAUSED → HALTED state
  machine. **PAUSE and HALT deliberately measure against different reference peaks.**
  PAUSE uses a trailing window (default 7 days): in a settle-to-flat book, a paused
  position set has frozen equity, so drawdown from an *all-time* peak can mathematically
  never shrink — an early version of this guard got permanently stuck paused and starved
  every out-of-sample test segment for three consecutive backtest runs. HALT uses the
  *all-time* peak on purpose — a trailing reference can't see a slow bleed that never
  drops 25%+ in any one window but adds up to well past the halt line. HALT is sticky;
  only an explicit human reset clears it.

## Strategy: crypto mispricing

Black-Scholes digital pricing (`N(d2)`) as the fair-value anchor, cross-checked by a
Student-t Monte Carlo simulation; a Kalshi-quoted YES/NO price that diverges from the
fee-adjusted fair value by enough triggers an entry, gated by minimum edge, probability
bounds, and BS/MC agreement. One gate was added after real validation runs, not designed
in up front: a **trend-regime filter** — the pricer assumes zero drift, and repeated
backtest losses traced to it fighting realized directional trends it had no way to see.
The engine now computes a drift z-score (recent log-return over the model's own expected
volatility scale) and holds when the market is trending harder than the zero-drift
assumption can explain.

See [Validation history](../status/validation-history.md) for what happened when this
strategy was actually run against history, in order — it's a better guide to how the
system behaves than any description of the code in isolation.

## Key data facts (verified against the live API)

- Kalshi's public API retains settled markets for only **~6 weeks** — the local DB is the
  real archive and must be refreshed regularly (see
  [Archiver operations](../runbooks/archiver-operations.md)).
- Hourly markets get exactly one 60-minute candle, timestamped at market close —
  backtesting them requires **1-minute candles**.
- Prices arrive as decimal-dollar strings (`"0.4500"`), volume as `volume_fp` strings;
  `data/kalshi/parse.py` is the single home for that format knowledge.
- Daily-temperature weather series trade far more of their strikes than crypto hourlies
  do (see [Project scope](../project-scope.md#why-weather-joined-crypto-as-an-active-pipeline-target)).

## Change workflow

Work is planned and tracked with [OpenSpec](https://openspec.dev/) under
`openspec/changes/`. Sequence: `core-data-and-backtesting` (active) →
`paper-trading-and-notify` (drafted, gated) → `dashboard-and-live-gate` → Webull options
(deferred) → AI/ML layer + weather/econ strategies. Each phase transition has explicit
go/no-go criteria — see [Roadmap](../roadmap.md).
