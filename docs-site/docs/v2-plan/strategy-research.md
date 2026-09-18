---
sidebar_position: 5
title: Strategy Research
---

:::info Source of truth
This mirrors `openspec/changes/v2-perps-scalping-and-frontend/strategy-research.md`. Edit the source file, not this page — republish after changes there.
:::

# Strategy research (task 2.1)

Five candidate families, each scored against published evidence, the market
conditions the edge depends on, and — the actual point of this exercise —
how it would be falsified on `KXBTC15M` data specifically. See `cost-floor.md`
for the win-rate bar each candidate must clear (50.45% maker-floor / 52.25%
taker-floor at a ~50¢ price, per task 2.2).

## 1. Order-flow imbalance (OFI)

**Claimed edge.** Net buyer- vs. seller-initiated trade pressure has a
documented near-linear relationship with short-horizon returns in market
microstructure theory, and this has been specifically validated on crypto
order-book data — a June 2026 SSRN paper (Vafin) consolidates order-flow
imbalance and short-horizon return predictability across crypto markets, and
the relationship is described as strongest "within tens of seconds."
([Vafin, SSRN 2026](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6938742);
[price-impact study, crypto order books](https://towardsdatascience.com/price-impact-of-order-book-imbalance-in-cryptocurrency-markets-bf39695246f6/))

**Conditions it needs.** A visible, liquid limit order book with enough
depth that imbalance is a meaningful signal rather than noise — exactly
`KXBTC15M`'s profile (234k+ OI, deep two-sided book), unlike the phantom
`KXBTCD` strikes. Needs the underlying spot/BRTI order flow, or Kalshi's own
book, refreshed fast enough to catch a "tens of seconds" signal.

**The catch, explicitly.** The same research notes the documented effect is
"usually not strong enough to be the source of statistical arbitrage" once
realistic transaction costs are applied — i.e., the academic literature
itself reports the edge is commonly smaller than round-trip cost. Combined
with `KXBTC15M`'s round-trip floor (50.45–52.25%, task 2.2), this is the
single biggest reason to be skeptical before building it.

**Falsification on `KXBTC15M`.** Compute OFI from Kalshi's own `yes_bid`/
`yes_ask` size deltas at 1-minute resolution against the next 1–3 candle's
directional move, on the accumulated archive. If the signal's realized edge
(win rate conditional on OFI direction) does not clear the maker-floor
(50.45%) *before* considering that Kalshi's book itself may already reflect
informed order flow (i.e., no exploitable lag), this strategy is falsified
and should not get a backtest slot per task 2.2's rule.

## 2. VWAP reversion

**Claimed edge.** A published framework (Bhatti, SSRN 2026, FX markets)
combines price extension from session VWAP with momentum-exhaustion signals
(ADX turning over) to time mean-reversion entries, reporting the strategy
works specifically in rotational/range-bound regimes and fails when a trend
is actually in place — the filter is what separates a survivable version
from one that "blows up." Industry sources report 55–65% win rates achievable
*with* proper regime filtering.
([Bhatti, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6454659))

**Conditions it needs.** A genuinely rotational/range-bound regime, and a
reliable way to detect "momentum exhaustion" before entering — exactly the
posture design.md explicitly ruled out for v2 (D2: "Phase 1 empirically
established that the zero-drift pricer loses by fading trends... v2 inverts
the posture: trade with short-term momentum"). VWAP reversion is structurally
a fade, which is the family of strategy that already failed once in this
project (Phase 1's run #6 OOS: 32.1% win vs 46.2% breakeven).

**Falsification on `KXBTC15M`.** Given the explicit trend-following mandate
in design.md D2, this strategy would need to demonstrate its regime filter
reliably distinguishes "safe to fade" from "trending, do not fade" on
`KXBTC15M`'s 15-minute bars specifically — not borrowed from FX/equity
regime behavior. If out-of-sample win rate during filter-flagged "range-
bound" periods does not clear 50.45%, or if the filter can't be shown to
avoid Phase 1's specific failure mode (fading an established 15-hour trend),
it is falsified. Given the direct conflict with D2, this is not
recommended for a backtest slot regardless of prior literature — see task
2.3 rationale.

## 3. Opening-range breakout (ORB)

**Claimed edge.** Backtested across ~150,000+ trades on equities, ORB shows
per-symbol win rates of 52–53% depending on the opening-range timeframe,
with the 15-minute variant specifically measured at 50.97% across 385,180
trades — right at the edge of breakeven before considering ORB-specific
edge in expectancy (reward:risk) rather than win rate alone. One quantified
backtest source explicitly states ORB "doesn't work very well anymore" in
its pure form; others report better results only with added filtering.
([ORB Setups research](https://orbsetups.com/research/opening-range-breakout-win-rate/);
[QuantifiedStrategies backtest](https://www.quantifiedstrategies.com/opening-range-breakout-strategy/))

**Conditions it needs.** A meaningful "opening range" concept — well-defined
on equities (market open) but `KXBTC15M` has no open/close in the equities
sense; it's a rolling 24/7 sequence of 15-minute binaries. The nearest
analog is `level_break.py`'s mandate (task 6.2): breakout of a level with
N confirming touches plus volume expansion, which is a more specific,
already-scoped version of this idea rather than a literal "opening range."

**Falsification on `KXBTC15M`.** Because there's no true session open,
treat this as already subsumed by `level_break.py` (task 6.2) rather than a
separate strategy — don't build ORB as a distinct fourth candidate. If
`level_break.py`'s backtested win rate (with volume confirmation) does not
clear 52.25% (its entries will typically need to cross the spread to catch
a breaking level, i.e., taker-floor applies), it's falsified on the same
basis the literature already half-expects (50.97% for the closest published
analog, well under either floor).

## 4. Funding-rate carry (perps)

**Claimed edge.** Documented as a genuinely market-neutral "cash and carry"
strategy: short perps + long spot (or the reverse), profiting purely from
the funding payment rather than direction. One study reports full-sample
mean returns around 8% with volatility of only 0.8% — a real, if modest,
risk-adjusted return, and by construction it doesn't need to predict BTC
direction at all.
([ScienceDirect funding-rate arbitrage study](https://www.sciencedirect.com/science/article/pii/S2096720925000818))

**Conditions it needs.** A funding rate extreme enough to be worth
collecting relative to the cost of holding the offsetting position — and,
per design.md, an event contract on the same BRTI index to hedge with
instead of spot (design.md's stated rationale for this being coherent here
at all — same reference index across instruments). Needs perps market data
(task 1.4, currently blocked on the authenticated client per §4).

**Falsification on `KXBTC15M`/perps.** This strategy doesn't get falsified
by `KXBTC15M` price data at all — it needs perps funding-rate history
(blocked, see tasks.md 1.4) and its own P&L is measured in funding collected
minus hedge cost/slippage minus fees on both legs, not win rate. It is
falsified if realized funding, net of hedge-leg transaction costs, does not
exceed the flat-fractional-risk-adjusted return of holding cash — i.e., if
the "market-neutral yield" doesn't beat the actual cost of running two
offsetting legs on Kalshi's fee schedule. Per design.md, this is already the
designated fallback if scalping strategies fail their gate (task 8.5) —
recommend prioritizing this for a research/backtest slot precisely because
it doesn't compete with the directional strategies for the same cost floor.

## 5. Momentum / pullback

**Claimed edge.** Published academic research (Petukhina, Reule & Härdle
2020; Wen, Bouri, Xu & Zhao, SSRN) specifically documents intraday return
predictability in cryptocurrency markets — both momentum and reversal
components — and finds economic value from timing strategies built on these
intraday predictors exceeds a buy-and-hold benchmark, including "strong
evidence of intraday time-series momentum even when previous returns are
negative."
([Wen et al., SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4135239_code2537556.pdf);
[Reading Univ. Bitcoin intraday momentum](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf))

**Conditions it needs.** An established short-term directional move to
trade with (not against), plus a defensible entry timing mechanism —
exactly `trend_scalp.py`'s scope (task 6.1: enter on pullbacks to respected
intraday levels within an established trend). This is the strategy family
design.md's D2 already commits to, and it's the one with the most direct
academic support of the five for the specific crypto/intraday setting.

**Falsification on `KXBTC15M`.** Define momentum via a short lookback
(e.g., prior N candles' net direction) and test whether entries on
pullback-and-hold within that momentum clear 50.45% (maker, if the pullback
entry can rest as a limit order at the level) or 52.25% (taker, if it must
chase). Also test the specific failure mode from Phase 1 (trading directly
into an already-exhausted trend) doesn't reappear — i.e., check performance
degradation isn't concentrated in trades entered late in a move. If
realized win rate doesn't clear its floor with margin, or if profit
concentrates in a handful of trades the way Phase 1's run #8 did (top-10
trades = 122% of test profit), it is falsified per task 8.4's gate criteria.

## Summary for task 2.3

| Candidate | Recommend for backtest slot? | Why |
|---|---|---|
| Order-flow imbalance | No | Literature itself reports the edge is typically smaller than transaction costs; would need to beat academic consensus on this project's exact fee/spread floor |
| VWAP reversion | No | Structurally a trend-fade — directly conflicts with design.md D2 and Phase 1's proven failure mode |
| Opening-range breakout | Subsume into `level_break.py` | No literal "session open" on a 24/7 15-min binary; `level_break.py` (task 6.2) already covers the underlying idea with a tighter, falsifiable spec |
| Funding-rate carry | **Yes — priority** | Market-neutral, doesn't compete for directional edge, already scoped (task 6.3), matches design.md's stated fallback priority |
| Momentum / pullback | **Yes** | Best-supported by published crypto-specific evidence, matches D2's trade-with-trend mandate, already scoped (task 6.1) |

Net effect: this research does not add new strategies beyond what tasks.md
§6 already scoped (`trend_scalp`, `level_break`, `funding_carry`) — it
confirms those three are the right three, gives each an explicit falsification
test tied to real cost-floor numbers, and rules out building OFI or VWAP
reversion as additional candidates. Selecting exactly these three (with ORB
folded into `level_break`) is the task 2.3 recommendation.
