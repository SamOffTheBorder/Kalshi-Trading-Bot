---
sidebar_position: 5
---

# Roadmap

Phased rollout with explicit go/no-go gates — no phase starts until the previous one's
gate is met. This mirrors the original architecture plan; the phase list is unchanged,
but the current position and near-term blocker below reflect where the project actually
is today, not where it was planned to be.

## Where we are right now

**Phase 1, blocked on §8.4.** The `core-data-and-backtesting` OpenSpec change has fully
built and tested the data pipeline, pricing signals, strategy, risk sizing, and backtest
engine (sections 1–7 of its task list). Section 8 — the actual gate review — found a real,
still-unconfirmed positive result after fixing four structural bugs; see
[Validation history](./status/validation-history.md) for the full run-by-run account.

### §8.4 frozen-config validation — the current blocker

Run #8's +10.2% out-of-sample margin can't be trusted at face value: the test window was
observed and reacted to across four prior iterations, so some of that margin is likely
the tuning process looking at its own answer key. The fix isn't more analysis — it's more
*calendar time*. The configuration is frozen exactly as of run #8 (trend z-score
threshold 1.5 over a 24h lookback, entry throttle of 3 per series per 24h, 25% liquidity
cap — all in `config/settings.py`), and the plan is:

1. Let the archiver accumulate genuinely new trading days after the freeze
   (2026-07-16) — data the tuning process never saw.
2. Re-run `scripts/run_backtest.py --split-date 2026-07-16` with **zero further tuning**
   once there's a comparable sample size to run #8's 64 test trades (roughly 1–2 weeks of
   new data, depending on how much the strategy trades day to day).
3. If the margin holds: take the Sharpe bar and drawdown thresholds to a proper gate
   review, and `paper-trading-and-notify` (drafted, see below) can begin.
4. If it doesn't hold: park `crypto_mispricing`, and pivot the same pipeline to the
   weather strategy family — which is why weather data has been archived in parallel
   since the freeze date rather than starting from zero if this happens.

This is purely a waiting game, not an engineering one — see
[Archiver operations](./runbooks/archiver-operations.md) for the one thing that actually
needs attention while it's in progress (keeping the archiver alive).

## Phase list

- **Phase 0 — Scaffold.** ✅ Done. `uv` pinned to Python 3.12, `openspec init`,
  Docusaurus scaffold, CI skeleton. *Gate: CI green, first change proposal written.*
- **Phase 1 — Data + backtest engine + strategy validation** (`core-data-and-backtesting`).
  🔶 In progress, blocked on §8.4 above. *Gate: out-of-sample Sharpe/win-rate/drawdown
  clears the bar on data the tuning process hasn't seen; signal/risk/engine test coverage
  exists.*
- **Phase 2 — Paper trading + notifications** (`paper-trading-and-notify`). 📝 Proposal
  and task list drafted early so this can start the moment Phase 1's gate clears;
  implementation has not begun. Builds the paper broker (inheriting the fill-realism
  rules earned in Phase 1), live Kalshi data path, `EmergencyControl` chokepoint, and
  Telegram/Discord bots. *Gate: ≥2–4 weeks unattended paper operation, results
  directionally consistent with the frozen-config backtest, all control commands verified
  from both Telegram and Discord.*
- **Phase 3 — Dashboard + ops visibility** (`dashboard-and-live-gate`, dashboard portion).
  Can overlap late Phase 2 since it's off the live-money critical path. FastAPI +
  React dashboard, port.io scorecard, Docusaurus content sync. *Gate: dashboard control
  actions verified to hit the same `EmergencyControl` chokepoint as chat commands;
  port.io scorecard green on emergency-stop coverage and secrets hygiene.*
- **Phase 4 — Live trading, small real capital.** Gated on *all* of: Phase 1's backtest
  bar cleared, Phase 2's paper window completed consistently, required tests green in CI,
  drawdown thresholds recalibrated against real backtest output, all emergency-stop paths
  manually verified live at least once. The first live week is watched specifically for
  v1's failure signature (win rate hovering near fee-adjusted breakeven) as an early stop
  signal, not just the drawdown guard.
- **Phase 5 — Webull options integration.** Deferred indefinitely — see
  [Deferred](#deferred) below.
- **Phase 6 — AI/ML layer + weather/econ strategy expansion.** FinBERT/Chronos-2
  backtested for genuine lift before being trusted live; Ollama regime classification and
  the OpenRouter veto validated against historical trade review before gating live
  trades. Weather strategy work may move earlier than Phase 6 if §8.4 leads to a pivot —
  see above.

## Deferred

**Webull (defined-risk options on liquid underlyings)** is fully deferred per explicit
user direction — not cancelled, just off the active roadmap until revisited. Nothing
should be built toward it (including the OpenAPI access application) in the meantime. The
original architecture (broker-specific `RiskModel`, sandbox-first, no naked/uncovered
writing) is preserved in the plan for whenever it's picked back up.

## Known operational risk

The local archiver (the thing keeping §8.4 moving) has stopped unresponsively multiple
times during Phase 1 — cleanly enough that it isn't a code crash, consistent with
something in the OS/session environment interrupting the console window it runs in. A
Windows Scheduled Task conversion would fix this structurally but was explicitly declined
in favor of keeping the visible console window; see
[Archiver operations](./runbooks/archiver-operations.md) for the current mitigation
(check and restart manually) and the tradeoff being accepted by not automating it.
