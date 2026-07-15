# Run a backtest

The backtest engine replays archived history through the **identical** strategy and risk
code the live loop will use — only the injected broker and data source differ. No strategy
graduates to paper trading (let alone live money) without clearing the gate here first.

## Prerequisites

- Archived 1-minute candles (see [Fetch historical data](./fetch-historical-data.md))
- Spot klines fetched (`--series --spot`)

## Commands

```bash
# Full archived window, default 25% test split:
uv run python scripts/run_backtest.py

# Most recent 14 days only, 30% test segment:
uv run python scripts/run_backtest.py --days 14 --test-frac 0.3

# Optimistic-fill sensitivity check (never use for the gate decision):
uv run python scripts/run_backtest.py --fill-mode midpoint
```

Strategy thresholds (min edge, divergence guard, probability bounds, Kelly fraction,
position cap, drawdown thresholds) all come from `.env` / `src/kalshi_bot/config/settings.py`.

## Reading the output

Each run prints train and test segments separately. **Only the test segment counts** for
the go/no-go decision — the split is enforced by the engine, not by discipline.

```
[test] trades=41 win_rate=58.5% vs breakeven=51.2% (margin +7.3%) net_pnl=+$4.12 (fees $1.88) sharpe=1.31 max_dd=6.2%
```

The single most important number is the **margin** — achieved win rate minus the
fee-adjusted breakeven win rate at the segment's average entry price. v1 of this bot ran
live at a "51% win rate" that was actually a net loss after Kalshi's 7% fee; this display
exists so that mistake cannot be re-made by misreading.

## Fill model honesty

Backtest fills are **pessimistic by default**: buying YES pays the bar's *highest* ask,
buying NO pays 100 minus the *lowest* bid, and the 7% fee is applied inside settlement.
If a strategy only makes money under midpoint fills, it doesn't have an edge — it has a
simulation artifact.

Every run persists to the `backtest_runs` table with its parameters and per-segment
metrics; every evaluation (including HOLDs, with reasons) lands in `signals`.
