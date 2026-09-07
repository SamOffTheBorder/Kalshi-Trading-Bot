---
sidebar_position: 2
---

# KXBTC15M validation rebuild — evidence taxonomy

The `kxbtc15m-validation-rebuild` OpenSpec change retired the v2 backtest results as
promotion evidence and rebuilt the validation path to be causal, KXBTC15M-scoped, and
honestly costed. This page is the operator-facing map of **what counts as what**.

Full detail lives in
[`openspec/changes/kxbtc15m-validation-rebuild/`](https://github.com/SamOffTheBorder/Kalshi-Trading-Bot/tree/main/openspec/changes/kxbtc15m-validation-rebuild)
(proposal, design, tasks). This is the summary.

## The four categories

### 1. Validated evidence

A result is **validated** only if it comes from a run stamped `evidence_class =
"validation"` — which means all of:

- **KXBTC15M only.** No other event series, no perps, mixed into the sample.
- **Causal timeline.** A decision made from the candle ending at *t* executes only
  against a *later* candle (§2.1/§2.2). No bar's close fills an order placed "during"
  that bar.
- **Full friction.** Entry taker fee *and* a modelled exit-leg fee, at the versioned
  `FeeConfig` coefficient. Side-aware YES/NO accounting (§2.3–2.5).
- **Fixed-risk sizing** derived from the executable stop distance and costs — **not
  Kelly** (§3.1).
- **Walk-forward with fresh per-fold state.** Every fold gets a new broker, cash
  ledger, and drawdown/daily guard; an embargo gap separates train from test (§3.3).
  Calibration (isotonic) is fitted on prior folds only.
- **Promotion gate applied** (§3.6): trade count, coverage, positive net expectancy
  with a day-blocked bootstrap CI excluding zero, Brier better than base rate. Miss
  any → **no paper capital.** A FAIL is retained, never deleted, and never counts as
  passing.

The dashboard's **Validation status** panel shows the current best validation run's
scope, data window, fee/resolution/calibrator versions, and the promotion verdict.

Everything from the v2 branch is `evidence_class = "diagnostic"` — kept for history,
not eligible for promotion.

### 2. Experiments (separately labelled)

Trend / pullback features (§4.4) run as a **conditioned variant** of the
settlement-aware baseline and are reported with their *incremental* out-of-sample value
after costs — never promoted on direction alone.

Microprice, public-trade imbalance, and quarter-hour-open effects (§4.5) are
**experiments**, reported separately from the baseline and each other.

### 3. Deferred (data-dependent)

These cannot run yet because the required data does not exist:

| Item | Blocked on |
| --- | --- |
| microprice | L2 order-book snapshots (`OrderBookSnapshot`) — none captured |
| public-trade imbalance | `PublicTrade` rows — none captured |
| quarter-hour-open effect | dense BRTI coverage at KXBTC15M window opens |
| Chronos-Bolt forecast backend (§7.2) | `torch` + `chronos-forecasting` deps not adopted |
| the veto benchmark (§7.5) | realized paper/live trade history |

Data collection is **manual and foreground-only** (`scripts/capture_session.py`) — no
scheduler, no unattended process. Deferrals are listed explicitly in the walk-forward
report, never silently skipped.

### 4. Disabled: cross-instrument funding carry

`strategy/funding_carry.py` is **research-only**. A binary event contract is not a
linear funding hedge, so a perp + event-contract pair is **not** market-neutral carry
— it is a directional perp bet with a funding kicker.

`classify_funding_carry()` (§5.2) returns `DISABLED` unless the hedge is a genuinely
linear instrument (spot / dated future / another perp) on the same reference index
**and** the rollover cadence, both legs' fees, per-interval funding accrual, and
residual basis risk are all modelled. Until then `evaluate_funding_carry` returns
`should_enter = False`, `market_neutral = False`.

Perp strategies have their **own** ledger, metrics, and promotion gate
(`backtest/perp_ledger.py`, §5.1) — separate from the binary-event report. The perp
gate rejects any liquidation, coming within 15% of liquidation, or leverage over 2×,
regardless of PnL. Perps go live only after their own gate **and** the event-contract
gate both pass.

## Data status and capture plan

**As of 2026-09-06 the validation pipeline is code-complete and tested, but no
run can render a merits verdict — the required data does not exist in the
archive and cannot be cheaply backfilled.** This is the single blocker for the
rebuild reaching paper trading.

### What the archive holds (`data/kalshi_bot.db`)

| Data | State |
| --- | --- |
| KXBTC15M settled markets | **6,444** — complete |
| KXBTC15M 1-minute contract candles | **~96,500**, 70 near-complete UTC days (2026-06-28 → 09-05) |
| `brti_observations` | **0 rows** — blocks the binary gate |
| perp mark price / funding rates / margin-market metadata | **no tables** — blocks any perp evaluation |

The contract side of KXBTC15M is essentially complete. The **BRTI index series
is entirely absent**, and KXBTC15M resolves off BRTI (60-second averages at open
and close, ties → YES) — not off Coinbase, Binance, or TradingView spot.

### Why BRTI cannot be backfilled

- A spot proxy (any exchange, TradingView) resolves a meaningful fraction of
  contracts differently from BRTI. The marginal trades live in the last ~1% of
  index noise, which is exactly where a proxy and BRTI diverge.
- CF Benchmarks sells historical BRTI; the free endpoint is real-time only.
- Causal discipline requires each reading stamped with both `observed_at` and
  `available_at` (when a live system could first have acted on it). A backfill
  cannot honestly reconstruct `available_at` — that reintroduces the look-ahead
  leak this rebuild exists to remove.

### BRTI source (resolved 2026-09-07)

BRTI is captured **live, forward-only** through Kalshi's authenticated CF
Benchmarks REST passthrough
(`GET https://external-api.kalshi.com/trade-api/v2/cfbenchmarks/values?id=BRTI`,
RSA-PSS signed, read-only market data). `kalshi_bot.data.brti.KalshiBRTISource`
drives it; `scripts/capture_session.py --poll-brti --brti-source kalshi` is the
loop. Smoke-tested live: real values returned, rows persisted with honest
`observed_at` / `available_at`.

**Operator: run `start_capture.bat`** (repo root) and leave the window open. It
refreshes contract candles and polls BRTI in ~6-hour cycles, foreground-only,
resumable. After the first cycle, `scripts/run_validation.py` prints the real
fill rate — a NO-GO is expected until ~71+ days accumulate.

### The capture plan

`scripts/capture_session.py`, **foreground only** — no scheduler, no service, no
unattended process. One session should poll **BRTI + KXBTC15M event quotes +
(ETH/SOL indices) + perp mark price + funding rate** together; the marginal cost
of extra endpoints is near zero and it yields binary *and* perp raw material in
the same window. Perp/margin endpoints are authenticated and each live
authenticated call needs explicit operator approval.

Sizing (assuming a conservative ~1% eligible-trade rate):

| segment | duration |
| --- | ---: |
| training window | 28 days |
| embargo | 1 day |
| test fold 1–3 | 14 days each |
| reserve for gaps / restarts | ~19 days |

Minimum contiguous geometry for three 14-day folds is **~71 days**; **90 days is
the recommended operator target**. Run a diagnostic `scripts/run_validation.py`
after ~3 test days to measure the real fill rate and re-plan — more calendar
time cannot repair a structurally inactive strategy, only an outage or data gap.

### Reusing the strategy for ETH / SOL / other Kalshi cryptos

The strategy *structure* generalizes; the *feed and data* are per-asset.

| Component | Reusable as-is? |
| --- | --- |
| `signals/settlement_window.py`, `strategy/settlement_prob.py`, `strategy/short_horizon_trend.py` | **Yes** — generic on any timestamped index series |
| Causal engine, walk-forward, promotion gate | **Yes** — already series-agnostic |
| Index feed | **No** — ETH resolves off a CF Benchmarks ETH index, not BRTI; each asset is its own capture |
| `ResolutionSpec` (window seconds, tie rule, index) | **No** — per contract |
| Captured data | **No** — per asset |

The `multi-asset-crypto-scalping` change provides the asset registry (per-asset
event series + index-feed mapping + lifecycle mode) this depends on.

## Promotion order if the event-contract gate fails

Per the v2 plan's §8.5 ordering, unchanged: **funding carry, then weather, then park.**
Parking is an acceptable, expected outcome.
