## Context

The existing bot has a fee-aware, liveness-aware event-contract backtest
engine and public Kalshi collection utilities, but they are configured around
crypto. The existing directional crypto strategies failed their fixed
out-of-sample gate, so this change investigates sports markets without
reopening that failed configuration or weakening the gate.

Sports data differs materially from crypto: market rules, participant status,
and settlement sources vary by event; live information is time-sensitive; and
displayed volume does not establish executable depth. The design therefore
starts with Kalshi market data and records enough provenance to reject a
result that cannot be replayed honestly.

## Goals / Non-Goals

**Goals:**

- Establish a read-only, operator-run sports market research pipeline.
- Screen for liquid, unambiguous, two-outcome single-game markets before
  storing or evaluating them.
- Test whether a calibrated candidate model contributes information beyond the
  contemporaneous Kalshi price after realistic execution costs.
- Produce a reproducible promote-or-park report, not a promising-looking
  backtest.

**Non-Goals:**

- Placing paper or live sports orders.
- Building a general sports data warehouse, scraping websites, or choosing a
  paid data vendor.
- Futures, multi-outcome outrights, player props, parlays/combos, arbitrage
  across external venues, or low-latency in-play execution.
- Treating win rate, model accuracy, raw volume, or gross PnL as evidence of
  an edge by themselves.

## Decisions

### D1 — Begin with a market-structure feasibility screen

The initial candidate universe is limited to Kalshi-listed, two-outcome,
single-game markets. A discovery pass decides which sport/series earns data
collection based on current rules, two-sided quotes, open interest, spread,
and displayed executable depth rather than choosing a league on popularity.

This avoids mixing fundamentally different contract shapes (e.g. season
futures, three-outcome draws, player props, and RFQ combos) into one model.
It also allows the first pilot to follow the liquidity actually available at
capture time.

### D2 — Kalshi is the required initial source; external data is an adapter

The initial pipeline uses Kalshi's public series, market, candle, order book,
and public-trade endpoints plus each market's stated settlement-source and
rule metadata. Any odds, lineup, injury, official live-play, or other
external feed is optional and has no default provider. It can be added only
through a source adapter that records its terms, endpoint, observed time, and
availability time.

This keeps the first study reproducible and avoids embedding an unapproved
commercial data dependency. It also makes the first question narrow: can the
project find a fee-adjusted edge from Kalshi's own market structure and
price-time behavior?

### D3 — Preserve causal time and rule provenance

Every captured observation carries exchange observation time when supplied,
local availability time, source endpoint, capture-session ID, and raw
provenance. A rule/settlement-source snapshot is attached to the market
identity used by a run. Missing order-book, trade, or game-state observations
are gaps, not values to interpolate.

The existing foreground-only collection policy remains in force: an operator
starts and stops each session, and no scheduler, service, or automatic
restart is added.

### D4 — The market is the benchmark, not a feature to beat by accuracy alone

The evaluator compares a candidate probability with the contemporaneous
Kalshi implied probability in fixed time-to-event buckets. Candidate signals
are calibrated only on prior data and assessed against a chronologically
untouched holdout. A simulated trade is permitted only when its edge clears
the actual series fee, quoted spread, configured slippage, and available
depth at the simulated fill.

This favors calibrated, selective value over an unconstrained winner-picking
model. It also prevents the common failure mode where a model has acceptable
classification accuracy but loses after friction.

### D5 — Separate research admission from trading admission

This change can label a candidate `research_promising` or `park`, but it
cannot enable paper or live execution. A future proposal may add paper
trading only if the feasibility report clears predeclared calibration,
execution, concentration, drawdown, and sample-size gates.

The separation keeps a small experimental dataset from becoming an implicit
authorization to trade capital.

## Risks / Trade-offs

- **[Sports books may be efficient]** → Benchmark against Kalshi's price and
  require a holdout advantage after costs; a better raw predictor is not
  sufficient.
- **[Displayed volume may not be executable]** → Record quoted size/depth and
  simulate partial or rejected fills instead of filling against volume.
- **[Rules and settlement differ by market]** → Store rule provenance and
  reject unknown, ambiguous, or non-binary contract shapes.
- **[Live data can leak future information]** → Use observed/available times,
  immutable capture sessions, and chronological splits.
- **[External data introduces cost, licensing, and latency risk]** → Keep it
  optional until a provider is deliberately selected and model value is shown.
- **[A short season or sparse pilot can create false confidence]** → Report
  uncertainty, concentration, and insufficient-sample outcomes explicitly.

## Migration Plan

1. Add only additive sports discovery and observation records; existing crypto
   rows and collectors remain unchanged.
2. Run discovery and manual capture in research mode.
3. Backtest a frozen candidate against an untouched sports holdout.
4. Publish a promote-or-park report. A failed or insufficient report leaves
   all sports execution paths disabled.
5. Rollback consists of disabling the optional sports capture commands; no
   existing production behavior or historical rows require removal.

## Open Questions

- Which independent source, if any, should provide official live game state or
  sharp external consensus after the Kalshi-only baseline is measured?
- What minimum observed depth and sample size are appropriate for the selected
  sport/market cadence?
- If the feasibility study passes, should the next proposal cover paper
  trading only, or a distinct data-provider integration first?
