# Proposal: v2-perps-scalping-and-frontend

> **Handoff document.** This is written to be read cold by another Claude (Opus) session
> with no prior context. Everything needed to start is here or linked from here.

## Why

Phase 1 (`core-data-and-backtesting`) built honest infrastructure and then used it to
prove its own strategy doesn't work. That is a success, not a failure — but the
conclusion must be respected rather than re-litigated. Four findings from that work
constrain everything below:

1. **The crypto strike-ladder markets are mostly untradeable.** Live sampling on
   2026-09-01 and 2026-09-04: of 100 open `KXBTCD` strikes, 8 had two-sided quotes;
   92 were 0¢/1¢ shells with zero open interest. The backtest was "filling" against
   phantom quotes (entries at 3¢, 4¢, 99¢), which is where its apparent profit came from.
2. **The BS/MC model is not calibrated.** Out-of-sample, the 40%-confidence bucket
   won 20% of the time — inverted. The model claimed +0.64 edge on a 3¢ contract.
   A zero-drift Black-Scholes cannot out-predict BTC direction, and the trend-regime
   gate added in Phase 1 is a patch over that fact, not a fix.
3. **Run #8's "first positive OOS result" was 10 trades.** Top-10 trades = 122% of
   test profit; the other 54 lost money collectively. Flat sizing turns $173 into $77.
   That is not an edge, it is variance plus Kelly compounding into phantom liquidity.
4. **The fee model was wrong.** Phase 1 modeled 7% of net winnings at settlement.
   Kalshi actually charges `0.07 × P × (1−P)` per contract **at entry, win or lose**,
   with makers paying ~¼ of that. Net effect was mildly favorable, but every fee
   calculation in the codebase is wrong and must be corrected before any new backtest.

v2 changes the instrument, the strategy family, the risk model, and the operator
surface — while keeping the parts of Phase 1 that were built correctly (storage schema,
data archiver, broker protocol, backtest engine skeleton, known-answer test discipline).

**The single most important discovery for v2:** `KXBTC15M` — "BTC price up in next
15 mins?" — is one binary contract per 15-minute window with **234,494 open interest
and 440,918 volume** on a single live contract (sampled 2026-09-04). Compare to the
hourly strike ladders where a typical strike shows OI of 15. This is the liquid
instrument the previous strategy needed and never had.

## What Changes

### Instruments (all on Kalshi, single venue, BTC-only)

Crypto-only by explicit decision — the weather series Phase 1 archived
(`KXHIGHNY`, `KXHIGHLAX`, etc.) are dropped from data collection and out of
scope for v2 strategy work. They remain in the historical database for
reference; nothing new is collected for them.

**BTC-only, further narrowed (2026-09-04):** ETH series (`KXETH`, `KXETHD`)
and ETH-USD spot klines are also dropped from data collection, same
treatment as weather — existing ETH rows stay in the DB for reference,
nothing new is fetched. v2's strategy work, archiver, and backtests target
BTC exclusively.

- **`KXBTC15M`** — binary, "BTC up in next 15 min", ~1¢ spread, very deep. Primary
  event-contract scalping instrument.
- **`KXBTCD` / `KXBTC`** — hourly strike ladders. Retained but **restricted to the
  ~8 near-the-money strikes that actually quote**; the phantom-strike filter is
  mandatory, not optional.
- **BTC perpetual futures** (`/margin` API) — linear USD-margined, 0.0001 BTC per
  contract (~$8 minimum position), funding every 8h at 00:00/08:00/16:00 ET capped
  at ±2%, max leverage ~5.9–6.1x, isolated margin (portfolio margin via API).
  Reference price is CF Benchmarks BRTI, same index the event contracts settle on —
  which is what makes cross-instrument strategies coherent here.

### Strategy family — replaces `crypto_mispricing`

The old strategy asked "what is fair value?" and traded the gap. v2 asks "what is the
market doing?" and follows it, with a fixed, small target. Consistency over magnitude,
per the stated goal of a 40–60% win rate with tight risk/reward.

- `strategy/trend_scalp.py` — trades **with** short-term trend, entering on pullbacks
  to respected intraday levels (recent swing highs/lows, session VWAP). Explicitly the
  opposite posture from Phase 1's mean-reversion, which lost by fading trends.
- `strategy/level_break.py` — breakout continuation when a level that has held N touches
  finally breaks with volume expansion.
- `strategy/funding_carry.py` (perps) — when the 8h funding rate is extreme, take the
  paid side and hedge directional exposure with the corresponding event contract.
  This is the one genuinely market-neutral idea in the set and the best fit for a small
  account; it earns funding rather than predicting direction.
- Research task (see `tasks.md` §2) to evaluate published short-horizon strategies
  (order-flow imbalance, VWAP reversion, opening-range breakout, funding-rate arb)
  and select which earn a backtest slot. **No strategy ships without clearing the gate.**

### Risk model — rebuilt for scalping and leverage

- **Server-side exit triggers.** Kalshi's margin API has native stop-loss / take-profit
  brackets and trailing stops (`/margin` exit-trigger endpoints). Every perps position
  gets a bracket **attached at entry, server-side** — so a disconnected bot, a crashed
  process, or a lost internet connection cannot leave a leveraged position unattended.
  This is non-negotiable and is the direct answer to "auto stop-losses."
- **Fixed R multiples.** Every trade defines risk `R` at entry; targets are expressed
  in R (e.g. 0.8R target / 1R stop for a ~55%-win-rate profile). Position size derives
  from R and account equity, not from Kelly.
- **Kelly is removed from the live path.** Phase 1 showed Kelly compounding into
  illiquid markets produces fantasy sizing (max position $172 on a $130 bankroll).
  v2 uses **flat fractional risk**: 1–2% of equity at risk per trade, hard cap.
- **Leverage cap well below the maximum.** Start at 2x, never above 3x, regardless of
  the 5.9x the exchange allows. At 5x a ~7% BTC move liquidates; at 2x there is room
  for the stop to work.
- **Daily loss limit** — N consecutive losses or X% daily drawdown halts trading until
  manually resumed. Retains Phase 1's `DrawdownGuard` state machine and
  `EmergencyControl` chokepoint design.

### Frontend — new

- Local web dashboard (FastAPI + server-rendered HTML/HTMX, no SPA build step) launched
  by a batch file: double-click → server starts → browser opens → dashboard is live.
  Trading does **not** auto-start; it starts from an explicit button in the UI.
- Shows: live positions with unrealized PnL, equity curve, open orders and their
  brackets, recent decisions **including HOLDs and the reason**, guard state, funding
  countdown, model/AI commentary, and a prominent kill switch.
- Replaces Docusaurus as the primary surface. Docs move to a `/docs` route inside the
  dashboard (or are dropped — see open question O4).

### AI layer — local-first

Hardware: **RTX 5070 (12GB VRAM)**, Ollama installed, 1000/day free OpenRouter requests.

- **Local (Ollama), fast path — every trade.** `qwen3:14b-q4_K_M` or
  `phi-4:14b-q4_K_M` (both fit 12GB at Q4_K_M) as the pre-trade sanity checker:
  structured JSON in, structured verdict out, ~1–3s. Deterministic prompt, low
  temperature, **fail-closed** (no response or malformed response = no trade).
- **Local, numeric path.** `Chronos-Bolt` (Amazon time-series foundation model) for
  short-horizon BTC forecasting — it is small, runs fast on a 5070, and is a genuine
  forecasting model rather than an LLM asked to do arithmetic it cannot do.
  FinBERT for headline sentiment classification (tiny, CPU-fine).
- **OpenRouter, slow path — not per-trade.** News/context retrieval, daily strategy
  review, weekly performance post-mortem. Free tier at 1000/day is ample for this
  cadence; paid credits are **not** recommended initially (see O5).
- **Explicit anti-goal:** no LLM decides entries. LLMs veto and annotate; the strategy
  and the numbers decide. An LLM asked "should I buy BTC?" produces confident noise.

## Capabilities

### New Capabilities

- `kalshi-authenticated-api`: RSA-PSS signed client for event contracts and `/margin`
  (perps) — orders, positions, fills, balance, funding, risk parameters, exit triggers
- `perps-trading`: leveraged BTC perpetual positions with server-side brackets,
  funding-rate awareness, and liquidation-distance monitoring
- `scalping-strategies`: trend-following / level-respecting short-horizon strategies
  targeting a consistent 40–60% win rate at fixed R multiples
- `fixed-risk-sizing`: flat fractional-risk position sizing with R-multiple targets,
  replacing Kelly on the live path
- `local-ai-review`: Ollama-hosted pre-trade veto + Chronos forecasting + FinBERT
  sentiment, fail-closed, with OpenRouter reserved for non-latency-critical context
- `operator-dashboard`: batch-file-launched local web UI for start/stop, live monitoring,
  and emergency halt

### Modified Capabilities

- `kalshi-market-data`: extend archiver to `KXBTC15M` and perps mark/funding history;
  add the mandatory two-sided-quote/OI liveness filter
- `risk-sizing`: Kelly retained for backtest comparison only; live path uses fixed risk
- `backtest-engine`: correct fee model; gate on **fill** price not intended price;
  add R-multiple and trade-concentration metrics to the gate criteria

### Removed Capabilities

- `crypto-mispricing-strategy`: parked. The zero-drift BS/MC pricer does not have an
  edge on BTC direction. Code stays in the repo for reference; it is not in the live path.

## Impact

- **Affected code:** `src/kalshi_bot/` — new `execution/kalshi_client.py`,
  `execution/kalshi_broker.py`, `execution/perps_broker.py`, `strategy/trend_scalp.py`,
  `strategy/level_break.py`, `strategy/funding_carry.py`, `risk/fixed_risk.py`,
  `risk/exit_triggers.py`, `ai/` package, `web/` package. Modified: `config/settings.py`,
  `data/kalshi/`, `backtest/`, `execution/backtest_broker.py` (fee fix).
- **Affected data:** archiver extended to `KXBTC15M` + perps; existing 15.5M candles retained.
- **Docs:** Docusaurus deprecated in favor of the dashboard.
- **Money:** $200–500. **No live capital until the gate in `tasks.md` §8 clears**, and
  first live money is event contracts only — perps go live only after event contracts
  have run profitably in paper for 2+ weeks.

## Open Questions (decide before or during implementation)

- **O1 — Archiver supervision — RESOLVED: no unattended process.** The user has
  decided against any background/scheduled/supervised process, including Windows
  Scheduled Task or NSSM. Historical data collection is manual: `KXBTC`/`KXBTCD`
  are pulled periodically via `fetch_historical.py`, run by hand whenever the
  operator chooses. Accepted trade-off: a missed check-in can lose data once it
  rolls off Kalshi's ~6-week window (already happened 4 times, most recently
  losing 2026-07-23 → 2026-09-04). No auto-restart, no staleness alarm — those
  only make sense for a process meant to run unattended, which this explicitly
  is not.
- **O2 — Perps sequencing.** The user asked to build perps support now. Recommendation
  stands that perps go live *after* event contracts prove out, even though the code is
  built in parallel. Confirm the user accepts that gating.
- **O3 — 15-min cadence vs. archiver — RESOLVED: no dedicated collector needed,
  the original premise was wrong.** Verified live 2026-09-04: `get_candlesticks`
  for a **settled** `KXBTC15M` market returns its full 1-minute bid/ask/OI/volume
  history (15 candles, complete) via the exact same endpoint already used for
  `KXBTC`/`KXBTCD`. `fetch_historical.py --series KXBTC15M --period 1` works
  end-to-end with zero code changes and pulled 300 candles over 20 markets in
  one run. The proposal's original worry — "the 30-minute pass will miss short
  windows entirely" — does not hold: Kalshi retains the quote/OI history for a
  settled 15-minute market the same as for any other settled market, within the
  same rolling window. No dedicated fast/near-real-time collector is needed;
  `KXBTC15M` just needs to be added to the series list, same as any other
  series. (Live-book snapshots of the currently-open contract, e.g. via
  `get_markets(status="open")`, are a nice-to-have for pre-settlement debugging
  but are not required for backtesting, since settled candlesticks already
  carry the tradeable history.)
- **O4 — Docusaurus.** Delete, or preserve as a `/docs` route in the new dashboard?
- **O5 — Paid OpenRouter credits.** Recommendation: no, initially. The per-trade path
  must be local for latency and cost reasons, and the slow path fits comfortably in
  1000 free requests/day. Revisit only if the daily-review quality is visibly limiting.
