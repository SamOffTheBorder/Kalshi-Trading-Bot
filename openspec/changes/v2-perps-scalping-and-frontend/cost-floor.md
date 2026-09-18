# Cost floor: KXBTC15M round-trip economics (task 2.2)

Computed from the corrected fee formula in `design.md` (not yet wired into
code — that's task 3.1). Order size used throughout: **20 contracts**,
representative of 1–2% risk on a $200–500 bankroll on a ~50¢ contract
(`fixed-risk-sizing`'s design point). Fee formula:

```
fee(P, n, coef) = ceil(coef × P × (1−P) × n × 100) / 100   dollars, TOTAL for the order
taker coef = 0.07, maker coef = 0.0175 (1/4 of taker)
charged once, at entry, win or lose. No settlement fee.
```

**Rounding note (verified 2026-09-04):** `ceil()` applies to the whole order,
not per contract. At `n=1` the fee looks worse than the textbook figure
(P=50 taker rounds to 2.00¢/contract, not 1.75¢) purely from rounding
granularity. At `n=20` (used here) and above, the per-contract fee converges
to the textbook curve. Do not eyeball fees at `n=1` — it overstates cost.

## Fee per contract across the price range (taker vs. maker, n=20)

| P (¢) | taker fee (¢) | maker fee (¢) |
|---:|---:|---:|
| 5  | 0.35 | 0.10 |
| 10 | 0.65 | 0.20 |
| 20 | 1.15 | 0.30 |
| 30 | 1.50 | 0.40 |
| 40 | 1.70 | 0.45 |
| **50** | **1.75** | **0.45** |
| 60 | 1.70 | 0.45 |
| 70 | 1.50 | 0.40 |
| 80 | 1.15 | 0.30 |
| 90 | 0.65 | 0.20 |
| 95 | 0.35 | 0.10 |

Peaks at P=50, symmetric, matches design.md's stated 1.75¢ taker peak
exactly. Maker is a genuine ~¼ of taker across the whole range — the "maker
fills matter" conclusion in design.md holds at every price level, not just
near 50¢.

## Two breakeven questions, and why they're different

**(1) Hold-to-settlement breakeven** — if a strategy buys a contract at P and
holds it to resolution (payoff $1 or $0), breakeven win rate is simply
`P + fee`. This is what `backtest/metrics.py`'s `breakeven_win_rate` computes
today (once task 3.1 fixes its fee input) — it is *not* the number that
matters for a scalping strategy, which exits early at a fixed target rather
than holding to settlement.

**(2) 1:1 R-multiple scalp breakeven** — the shape `scalping-strategies`
actually uses (task 6, fixed R target/stop, exit early via the opposing
side). Cost here is fee-on-entry + fee-on-exit + spread-crossing on both
legs if taker. This is the number tasks.md 2.2 is actually asking for.

| Leg style | Cost floor (round trip, any price ~10–90¢) |
|---|---:|
| Taker both legs (crosses 1¢ spread twice) | ~51.15%–52.25%, peaking at ~52.25% near 50¢ |
| Maker both legs (no spread cross) | ~50.20%–50.45%, peaking at ~50.45% near 50¢ |

## The tasks.md 2.2 worked example, corrected

Original estimate in tasks.md: *"1¢ spread + 1.75¢ taker fee ≈ 2.75% per
round trip → ~52.8% win rate."* That estimate only counted the fee/spread
**once** (as if only the entry leg pays it). A 1:1 R scalp pays the fee on
**both** entry and exit, and if taker, crosses the spread on **both** legs
too. Computed properly at P=50¢:

- **Taker, both legs:** fee = 1.75¢ × 2 = 3.5¢, spread = 1¢ × 2 = 2¢ →
  **5.50% round-trip cost → 52.25% breakeven win rate.**
- **Maker, both legs:** fee = 0.45¢ × 2 = 0.9¢, no spread cost →
  **0.90% round-trip cost → 50.45% breakeven win rate.**

The taker breakeven (52.25%) lands close to the original 52.8% estimate by
coincidence — the original undercounted the fee (single leg) but also didn't
apply it as cleanly to the R-multiple math; the corrected number is still
in the "just above half" zone the proposal expected, but maker execution
makes an enormous difference: **50.45% vs. 52.25% is the entire margin most
40–60%-target scalping strategies are trying to clear.** This is the same
conclusion design.md already drew qualitatively ("design for maker fills
wherever the strategy's latency budget allows") — this document is the
quantitative backing for it, computed across the full price range rather
than asserted at one point.

## Gate implication (ties to task 8.4)

A strategy that cannot realistically achieve **maker fills on both legs**
needs a backtested win rate clearing ~52.25% with margin to pass the cost
floor at *any* price level near 50¢ (the zone `KXBTC15M` trades in most of
the time, since it's a coin-flip-shaped market). A strategy that reliably
gets maker fills only needs to clear ~50.45% — a materially easier bar, and
the reason `funding_carry` (perps, market-neutral, doesn't need directional
edge at all) remains the most defensible idea in the set per design.md.

**Recommendation for task 2.3:** score each candidate strategy's realistic
win rate against **both** thresholds (52.25% taker-floor, 50.45% maker-floor)
using its expected fill style, not a single blended number. A strategy that
clears 50.45% but not 52.25% is not dead — it's a strategy that must be
disqualified from live trading unless it can be executed maker-side, which
is an execution-design constraint to solve, not a backtest number to fudge.

## Reproducing this

Computed by a standalone script (not committed — this is a research
deliverable per tasks.md §2, "no code changes to the live path"). Formula
and constants are transcribed in this document; task 3.1 will wire the
corrected formula into `execution/backtest_broker.py`, `risk/kelly.py`, and
`backtest/metrics.py`, at which point the code becomes the source of truth
and this document should be checked against it.
