---
sidebar_position: 3
---

# Run a backtest

The backtest engine replays archived history through the **identical** strategy and risk
code the live loop will use — only the injected broker and data source differ. No strategy
graduates to paper trading (let alone live money) without clearing the gate here first.
See [Validation history](../status/validation-history.md) for what running this against
real data has actually found so far.

## Prerequisites

- Archived 1-minute candles (see [Fetch historical data](./fetch-historical-data.md))
- Spot klines fetched (`--series --spot`)

## Commands

```bash
# Full archived window, default 25% test split:
uv run python scripts/run_backtest.py

# Most recent 14 days only, 30% test segment:
uv run python scripts/run_backtest.py --days 14 --test-frac 0.3

# Pin the train/test split at a fixed date instead of a fraction — everything after it
# is guaranteed unseen. This is the command for §8.4 frozen-config validation:
uv run python scripts/run_backtest.py --split-date 2026-07-16

# Optimistic-fill sensitivity check (never use for the gate decision):
uv run python scripts/run_backtest.py --fill-mode midpoint
```

Strategy thresholds (min edge, divergence guard, probability bounds, trend-regime
z-score, entry throttle, Kelly fraction, position cap, liquidity cap, drawdown
thresholds) all come from `.env` / `src/kalshi_bot/config/settings.py` — there is exactly
one place these numbers are defined.

:::warning Frozen-config discipline
As of run #8, the configuration is **frozen** pending [§8.4 validation](../roadmap.md#84-frozen-config-validation--the-current-blocker).
Do not adjust `min_edge`, `max_trend_zscore`, `max_entries_per_series_window`,
`liquidity_cap_frac`, or any other strategy/risk setting based on a backtest result
until that validation completes — every prior "fix" was legitimate precisely because it
was diagnosed from a *structural* audit (an actual bug in the code), not from nudging a
number until the output looked better.
:::

## Reading the output

Each run prints train and test segments separately. **Only the test segment counts** for
the go/no-go decision — the split is enforced by the engine, not by discipline.

```
[test] trades=64 win_rate=60.9% vs breakeven=50.8% (margin +10.2%) net_pnl=+$173.47 (fees $40.24) sharpe=0.72 max_dd=29.1%
```

The single most important number is the **margin** — achieved win rate minus the
fee-adjusted breakeven win rate at the segment's average entry price. v1 of this bot ran
live at a "51% win rate" that was actually a net loss after Kalshi's 7% fee; this display
exists so that mistake cannot be re-made by misreading.

## Fill model honesty

Backtest fills are **pessimistic by default**: buying YES pays the bar's *highest* ask,
buying NO pays 100 minus the *lowest* bid, the 7% fee is applied inside settlement, and
fills are capped at a fraction of the bar's actual traded volume (`liquidity_cap_frac`,
default 25% — added after a real run compounded a position past a market's entire
lifetime volume; see [Validation history — run #7](../status/validation-history.md#run-7--the-trend-hypothesis-confirmed-fills-exposed-as-unrealistic)).
If a strategy only makes money under midpoint fills or uncapped liquidity, it doesn't
have an edge — it has a simulation artifact.

Every run persists to the `backtest_runs` table with its parameters and per-segment
metrics; every evaluation (including HOLDs, with reasons) lands in `signals`.
