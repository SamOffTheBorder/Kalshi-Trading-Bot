---
sidebar_position: 2
title: Design
---

:::info Source of truth
This mirrors `openspec/changes/v2-perps-scalping-and-frontend/design.md`. Edit the source file, not this page — republish after changes there.
:::

# Design: v2-perps-scalping-and-frontend

## Context

Read `proposal.md` first. This document records the technical decisions and the
verified facts behind them, so the implementing session does not have to re-derive
or re-research them.

### Verified facts (sampled live 2026-09-01 and 2026-09-04)

**Kalshi API payload shape.** Money fields are strings named `*_dollars`
(`yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`, `liquidity_dollars`);
size fields are `*_fp` (`open_interest_fp`, `volume_fp`). The legacy integer-cent
fields (`yes_bid`, `volume`, `open_interest`) return `None`. `data/kalshi/parse.py`
is the single home for this knowledge — keep it that way.

**Liquidity reality.**

| Series | Shape | Observed liquidity |
|---|---|---|
| `KXBTC15M` | one binary per 15-min window, "BTC up in next 15 mins?" | **OI 234,494 / vol 440,918** on the single live contract, 1¢ spread |
| `KXBTCD` | hourly strike ladder | 60 open, 23 two-sided; typical strike OI **15** |
| `KXBTC` | hourly strike ladder | 60 open, 10 two-sided; OI 0–1,671 |
| Weather (`KXHIGHNY`, `KXHIGHLAX`) | daily temp ladder | every strike quoted, 1¢ spreads, OI 171–25,935 |

`KXBTC15M` resolution rule: resolves YES if the 60-second BRTI average before the
window close is **at least** the 60-second BRTI average before the window open.
Note "at least" — exact ties resolve YES. This matters for a strategy trading near 50¢.

**Kalshi fee schedule (current, corrected).**
- Taker: `ceil(0.07 × P × (1−P) × contracts × 100) / 100` dollars, charged **at entry**,
  win or lose. Peaks at 1.75¢/contract at P=0.50.
- Maker: same formula with coefficient `0.0175` (¼ of taker).
- **No settlement fee.** The formula evaluated at P=0 or P=1 is zero.
- Recomputing Phase 1's run #8 under the correct model: test net $173.47 → **$184.77**
  taker / **$206.22** maker. Maker-vs-taker is a ~4x fee difference — resting limit
  orders instead of crossing the spread is worth ~$21 on $214 gross. **Design for
  maker fills wherever the strategy's latency budget allows.**

**BTC perpetual contract specs.**
- Contract size 0.0001 BTC (~$8/contract), minimum position 1 contract
- Linear, USD-margined; isolated margin in apps, portfolio margin available via API
- Funding every 8h at 00:00 / 08:00 / 16:00 ET, capped ±2% per interval
- Max leverage ~5.9x BTC (some sources say 6.1x as of Aug 2026) — **v2 caps at 2x**
- Settlement cycles 12:00 PM and 4:00 PM ET; trades 24/7 except maintenance
- Reference index: CF Benchmarks BRTI, updating every second — **the same index
  `KXBTC15M` and `KXBTCD` settle against**, which is what makes hedging coherent

**Margin API surface** (from `docs.kalshi.com/llms.txt`): orders (create/cancel/amend/
decrease/cancel-all), positions, fills, balance, subaccounts and transfers, orderbook,
candlesticks, public trades, fee tiers, **funding history / historical rates / current
estimate**, risk parameters (system-wide liquidation thresholds), per-position risk
(leverage + liquidation price), notional risk limits, order groups, and **exit triggers
(isolated and cross stop-loss/take-profit brackets, trailing stops, cancel-by-id)**.
WebSocket channels: orderbook, ticker (incl. mark price), public trades, and
authenticated user fills/orders.

## Goals / Non-Goals

**Goals**
- One venue (Kalshi), two instrument types (event contracts + perps), one BRTI index
- Consistent small wins: 40–60% win rate at fixed R, not occasional large ones
- Risk that survives a crashed process — server-side brackets, not in-process logic
- An operator surface that starts from a batch file and can stop trading instantly
- AI that assists and vetoes, never decides

**Non-Goals**
- Maximizing leverage. 5.9x is available; 2x is the design point.
- LLM-generated trade signals.
- Reviving `crypto_mispricing`. It is parked with cause.
- High-frequency / sub-second execution. Kalshi REST + WS is not that venue, and the
  15-min cadence does not require it.
- A JS SPA frontend. Server-rendered HTML keeps the batch-file launch trivial.

## Decisions

### D1 — `KXBTC15M` is the primary event-contract instrument

The Phase 1 post-mortem's central lesson is that liquidity, not modeling, was the
binding constraint. `KXBTC15M` has ~4 orders of magnitude more open interest than a
typical hourly strike. It is also structurally simpler: one binary, no strike selection,
no ladder to filter. A 15-minute horizon suits scalping and produces ~96 windows/day,
which means a statistically meaningful sample accumulates in weeks rather than months —
directly addressing Phase 1's "10 trades decided the result" problem.

**Consequence (revised, O3 corrected 2026-09-04):** originally assumed a dedicated
fast collector was needed because a 30-minute pass "misses" a 15-minute market.
Verified live: it doesn't. `get_candlesticks` for a settled `KXBTC15M` market
returns its complete 1-minute bid/ask/OI/volume history, same as any other
settled market, within Kalshi's normal rolling window. Adding `KXBTC15M` to the
existing series list is sufficient — `fetch_historical.py` needed zero changes.
No dedicated near-real-time collector was built.

### D2 — Trend-following replaces mean-reversion

Phase 1 empirically established that the zero-drift pricer loses by fading trends
(run #6 OOS: 32.1% win vs 46.2% breakeven), and the `trend_zscore` gate was a patch
that suppressed trading rather than a source of edge. v2 inverts the posture: trade
**with** short-term momentum, enter on pullbacks to levels that have held, exit fast at
a fixed target.

Level definition (deterministic, no discretion): swing highs/lows over a lookback
window, confirmed by N touches within a tolerance band, plus session VWAP. A level is
"respected" when price approaches within the band and reverses without closing through.

### D3 — Fixed fractional risk, not Kelly

Kelly requires a trustworthy win-probability estimate. Phase 1's calibration table
(model says 40% → wins 20%) proves that estimate does not exist yet. Kelly also
compounds — which, combined with phantom liquidity, produced a $172 position on a
$130 bankroll.

Live sizing: risk 1–2% of equity per trade. `R` = distance from entry to stop.
Contracts = `(equity × risk_pct) / R`. Kelly stays in the codebase for backtest
comparison so the two can be measured against each other, but it does not size live orders.

### D4 — Server-side brackets are mandatory

Every perps entry attaches a stop-loss and take-profit via Kalshi's exit-trigger
endpoints **in the same logical operation as the entry**, before the bot considers
the position open. Rationale: this bot's own operational history includes four silent
process deaths. In-process stop logic would have left leveraged positions unmanaged
during each one. If the bracket cannot be attached, the position is closed immediately.

Event contracts have defined max loss (entry cost) so brackets are optional there —
but a take-profit is still used to realize the small, consistent target.

### D5 — Local AI for the fast path, OpenRouter for the slow path

Latency and cost both point local for anything per-trade. On 12GB VRAM at Q4_K_M:
`qwen3:14b` or `phi-4:14b` fit with room for context and answer in ~1–3s. The veto
prompt is structured (numbers in, JSON verdict out) and low-temperature, and the gate
is **fail-closed**: no/malformed response means no trade.

`Chronos-Bolt` handles short-horizon numeric forecasting — a purpose-built time-series
foundation model rather than an LLM doing arithmetic. FinBERT handles headline
sentiment on CPU.

OpenRouter's free 1000/day covers news retrieval, a daily strategy review, and a weekly
post-mortem — none latency-critical. Paid credits are not recommended until there is
evidence the free tier constrains quality (O5).

### D6 — Server-rendered dashboard, not an SPA

FastAPI + Jinja + HTMX. No `npm install`, no build step, no bundler — the batch file
starts `uvicorn` and opens a browser. Live updates via WebSocket or HTMX polling.
This keeps the "double-click to trade" requirement genuinely one step, and avoids
adding a Node toolchain to a Python project.

**Trading does not auto-start when the server starts.** The dashboard opens in a
stopped state with an explicit Start button, so opening the UI to look at history is
never the same action as putting money at risk.

## Risks / Trade-offs

- **Perps + leverage + unvalidated strategy is the highest-risk combination in this
  project's history.** Mitigations: 2x cap, server-side brackets, 1–2% risk per trade,
  daily loss limit, perps gated behind event contracts proving out in paper first.
- **15-minute windows are close to a coin flip.** BTC over 15 minutes is nearly a random
  walk; a 40–60% win rate target is realistic *only* if fees and spread are beaten,
  which is why maker fills matter so much (D-fees above). If the strategy needs to cross
  a 1¢ spread on a ~50¢ contract, taker fees (1.75¢) plus spread is ~2.75¢ of a 100¢
  contract — roughly 2.75% per round trip, needing ~52.8% win rate just to break even.
  **This must be modeled explicitly in the backtest before anything goes live.**
- **Funding carry is the most defensible idea and may deserve priority.** It earns a
  fee rather than predicting direction. If the directional scalping strategies fail the
  gate, funding carry is the fallback rather than another round of tuning.
- **Archiver fragility remains the top operational risk** and has already cost ~6 weeks
  of irreplaceable data. Per the user's explicit decision (O1), this is accepted rather
  than engineered away: no unattended process runs, so a missed manual check-in can
  still lose data. Mitigated only by keeping the manual-fetch cadence tight, not by
  automation.

## Migration Plan

1. Trim the archiver to crypto-only and extend to `KXBTC15M` + perps (O1 note: no
   supervision/auto-restart is built — collection is manual/operator-run) — **first,
   before any strategy work**, because every subsequent step needs data that only
   accumulates forward.
2. Correct the fee model and the fill-vs-intended-price gating bug in the backtest engine;
   re-run Phase 1's run #8 as a regression check on the corrected engine.
3. Build the authenticated client (read-only first: balance, positions, fills), verified
   against the demo environment.
4. Build strategies + fixed-risk sizing; backtest against accumulated `KXBTC15M` data.
5. Gate review. Only then: paper trading, then live event contracts, then perps.
6. Dashboard and AI layer can proceed in parallel with 3–4; neither is on the critical path.

## Rollback

Every phase is additive. `crypto_mispricing` and the Kelly sizer stay in the tree.
If v2's strategies fail their gate, the fallback order is: funding carry (market-neutral),
then the weather strategy Phase 1 identified as promising (daily temp markets are the
most liquid instruments on the exchange), then park live trading entirely and keep
archiving. **"Park it" is an acceptable outcome and must stay on the table** — the
failure mode this project is structurally guarding against is trading an unvalidated
edge because effort was already spent.
