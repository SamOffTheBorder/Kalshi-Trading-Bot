---
sidebar_position: 1
---

# Validation history

The single most important question this project can ask about any strategy is: **does it
actually have an edge, measured honestly?** This page tracks every real backtest run
against that question, in order, including the runs that failed — because the failures
are what found and fixed four separate structural bugs before any of them could have cost
real money.

Full detail (methodology, audit-trail queries, exact numbers) lives in
[`openspec/changes/core-data-and-backtesting/notes.md`](https://github.com/SamOffTheBorder/Kalshi-Trading-Bot/blob/main/openspec/changes/core-data-and-backtesting/notes.md)
in the repo — this page is the narrative summary.

## Current state: gate not cleared, config frozen, awaiting fresh data

As of run #8 (2026-07-16), the strategy produced its **first positive out-of-sample
result** — but the config was tuned while watching that same test window across four
prior runs, so that result cannot be trusted at face value. The configuration is now
**frozen** and the plan is to re-run on calendar days that did not exist when tuning
stopped, with zero further adjustment, before drawing a conclusion. See
[§8.4 in the roadmap](../roadmap.md#84-frozen-config-validation--the-current-blocker) for
what "enough new data" means and why it isn't just a data-volume question.

## Run-by-run

| Run | Date | Window | Train margin | Test margin | Verdict |
|---|---|---|---|---|---|
| #3 | 07-15 | 12 days | -6.5% | *(no OOS trades)* | Not cleared — dollar-weighted profit masked a losing win rate |
| #4 | 07-16 | 67 days | -15.8% | *(no OOS trades)* | Not cleared — worse with more data, not better |
| #5 | 07-16 | 67 days + entry throttle | -1.1% | *(no OOS trades)* | Throttle worked; guard bug still starving test segment |
| #6 | 07-16 | 67 days + guard fix | -0.3% | **-14.0%** | First real OOS segment — fails decisively |
| #7 | 07-16 | + trend-regime gate | +0.5% | -0.7% | Trend hypothesis confirmed; fill model exposed as unrealistic |
| #8 | 07-16 | + liquidity-capped fills | +5.7% | **+10.2%** | First positive OOS margin — gate still not cleared (see below) |

"Margin" is achieved win rate minus the fee-adjusted breakeven win rate at that segment's
average entry price — the number that would have caught v1's "51% win rate" as the net
loser it actually was.

### Run #3 — the metrics design did its job

12 days of data, 37 trades, net PnL **+$68.95** — which looked like a win until the
breakeven comparison showed it wasn't. Win rate 59.5% against a fee-adjusted breakeven of
66.0% at that segment's average entry price: the profit came from favorable
dollar-weighting on a small sample, not a validated per-trade edge. This is exactly the
failure signature the side-by-side breakeven display exists to catch. A 25.8% drawdown
also tripped the pause guard mid-run, so the test segment got zero trades and the gate
couldn't even be evaluated.

### Run #4 — worse with more data, and a hidden cluster

67 days, only 23 trades, margin widened to **-15.8%**, net PnL genuinely negative. Auditing
the trade list found the real story: **all 23 trades fired within one ~15-hour window on
a single day**, almost entirely on the NO side at adjacent strikes near $78,000 — the
strategy was repeatedly fighting one trending move, not sampling diverse conditions. A
"67-day backtest" was actually a "15-hour episode" wearing a longer window's clothes.

### Run #5 — the cluster cap works, a new bug surfaces

Adding a per-series rolling entry cap (max 3 entries per series per 24h) spread the same
strategy's entries across 16 distinct days instead of one 15-hour cluster. Margin improved
**-15.8% → -1.1%**. But the test segment was *still* empty — the third run in a row with
zero out-of-sample trades, which meant the gate literally could not be evaluated no matter
how good the strategy was.

### Run #6 — the stuck-guard bug, found and fixed

Root cause of the empty test segments: the drawdown guard measured drawdown against an
**all-time peak**. In a book that settles to flat while paused, equity is frozen, so
drawdown from an all-time peak can mathematically never shrink — once paused, the guard
stayed paused for the rest of every run, including the entire test window. Fixing this to
use a trailing peak (so an old high ages out and the guard can re-arm) finally produced a
real out-of-sample segment: 28 test trades, **32.1% win rate against a 46.2% breakeven —
a decisive, honest failure.** The system was doing exactly what it was built to do.

### Run #7 — the trend hypothesis confirmed, fills exposed as unrealistic

Every audit up to this point pointed the same way: the pricing model assumes zero drift
and keeps losing to real directional moves. Adding a trend-regime gate (hold when recent
realized drift exceeds what the model's own volatility would predict) moved the OOS
margin from **-14.0% to -0.7%** — the hypothesis held. But the run's headline number
(\$130 → \$10,690) was fantasy: the biggest fills exceeded the *entire lifetime volume* of
the markets they traded in. No real order book absorbs a 29,747-contract fill in a market
that only ever traded 54,066 contracts. The fill model had no liquidity limit.

### Run #8 — first positive result, and the reason it still isn't a green light

Capping fills at 25% of a bar's actual traded volume produced the first honest, positive
out-of-sample result: **64 test trades, 60.9% win rate against a 50.8% breakeven, +10.2%
margin, Sharpe 0.72, net +\$173.47**. The structure looks real — no single trade dominates
the total, entries spread across 12 days at a sane rate, and (notably) *tightening* the
fill model improved the result, which is the reassuring direction: it means the earlier
numbers were inflated by unrealistic fills, not that realism is hiding a loss.

It still doesn't clear the gate, for two reasons: OOS Sharpe (0.72) is below the >1.0 bar,
and — more importantly — **the test window has now been looked at four times during
iteration.** Every fix from run #4 onward was chosen after seeing how it affected that
same segment. A margin measured that way has to be treated as tuned-in until it's checked
against data the tuning process never saw.

## What changed in the codebase because of this

Four structural fixes, none of which were anticipated in the original design — all found
by actually running the strategy against history and refusing to accept a good-looking
number without asking why:

1. `risk/entry_throttle.py` — per-series rolling entry cap
2. `risk/drawdown_guard.py` — trailing peak for PAUSE, all-time peak for HALT
3. `strategy/crypto_mispricing.py` + `backtest/engine.py` — trend-regime gate
4. `execution/backtest_broker.py` — liquidity-capped fills

Each is described in more detail in
[Architecture → Risk management](../architecture/overview.md#risk-management) and
[Architecture → Strategy: crypto mispricing](../architecture/overview.md#strategy-crypto-mispricing).
