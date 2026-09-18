## Why

The bot is accumulating the first causally usable crypto event-market and perpetual datasets,
but it does not yet have a preregistered portfolio of hypotheses that says which strategies are
worth testing, what data each needs, or what evidence would kill an idea. Defining that portfolio
before the longer history exists reduces hindsight tuning and makes the eventual tests useful
rather than another collection of optimistic backtests.

## What Changes

- Create a ranked research portfolio for crypto perpetuals and prediction markets, with every
  candidate labeled `priority`, `incubator`, `benchmark`, or `reject` and assigned a written
  economic mechanism, required inputs, falsification test, and independent promotion gate.
- Prioritize these perpetual experiments:
  - reference-basis dislocation and convergence;
  - cost-aware short-horizon momentum/pullback and level-break continuation;
  - quarter-hour/session-boundary flow effects as a feature, not a standalone claim;
  - cross-asset relative strength as a later multi-leg experiment;
  - funding as a regime/cost feature, while keeping “market-neutral funding carry” disabled until
    a compatible linear hedge and full rebalance economics exist.
- Prioritize these prediction-market experiments:
  - settlement-aware probability nowcasting with trend, volatility, distance-to-target, and
    observed settlement-window inputs;
  - final-window BRTI projection using only the observed portion of the published averaging
    window;
  - cross-strike probability-ladder consistency and executable arbitrage checks;
  - external-venue-to-Kalshi lead/lag and order-flow features, conditional on sufficiently dense
    causal book/trade capture;
  - cross-horizon consistency between compatible 15-minute, hourly, and daily contracts as a
    later experiment.
- Retain no-trade, market-implied probability, simple momentum, and naive basis-reversion
  benchmarks so complex candidates must demonstrate incremental value.
- Explicitly reject or quarantine naive zero-drift Black-Scholes/Monte-Carlo mispricing, unfiltered
  mean reversion, candle-range maker fills, binary-contract “linear” hedges, and any pooled
  multi-asset promotion result.
- Add a frozen experiment registry, data-qualification matrix, multiple-hypothesis budget,
  walk-forward/embargo protocol, realistic execution models, and permanent rejected-result
  reporting.
- Produce research reports and dashboard-ready summaries only; this change does not authorize live
  trading or automatically promote a strategy.

## Capabilities

### New Capabilities

- `crypto-strategy-research-portfolio`: Ranked perpetual and prediction-market hypotheses,
  benchmarks, prerequisites, falsification rules, and lifecycle states.
- `crypto-strategy-research-data`: Causally aligned, provenance-preserving feature datasets and
  explicit qualification gates for each candidate family.
- `crypto-strategy-experiment-governance`: Frozen experiment plans, walk-forward evaluation,
  realistic cost/fill modeling, multiple-testing control, and reproducible promotion/rejection
  reports.

### Modified Capabilities

None. This change consumes the contracts being built by `kxbtc15m-validation-rebuild`,
`multi-asset-crypto-scalping`, and `strategy-lab-multi-account` without weakening or silently
rewriting them.

## Impact

- Affects future work in `src/kalshi_bot/strategy`, `src/kalshi_bot/backtest`, crypto data capture,
  dataset manifests, experiment storage, reporting, and the Strategy Lab dashboard.
- Depends on source-native timestamps, fresh perp marks/order books, funding history, native BRTI,
  external spot/perp bars and trades, event-market quotes/books/trades, settlement metadata, and
  complete fee/contract specifications.
- Reuses the existing asset registry, causal availability timestamps, isolated ledgers, paper-run
  audit trail, and validation/promotion policy rather than creating a parallel research engine.
- Adds no exchange mutation, live-order route, external notification, or automatic allocation.

## Model complexity

Complexity is **high**: strategy selection spans two payoff types, multiple synchronized venues,
causal feature construction, nonlinear settlement, funding and liquidation economics, realistic
fills, multiple-hypothesis risk, and long-context reconciliation with several active OpenSpec
changes. Evaluation risk is higher than coding risk because a plausible but leaky backtest would be
more harmful than an explicit no-edge result.

- Use **GPT-6 Astra** at high or xhigh effort, or **Claude Opus 5**, for architecture, economic
  assumptions, leakage review, promotion gates, and final evidence review.
- Use **GPT-5.6 Terra** or **Claude Sonnet 5** for bounded dataset adapters, deterministic feature
  implementations, reports, fixtures, and dashboard presentation after the contracts are frozen.
- A lighter model may handle mechanical documentation or repetitive fixtures, but it must not
  change timestamps, labels, cost models, hedge classification, multiple-testing policy, or
  promotion criteria.
- Escalate to the stronger model when an instrument's payoff/fee semantics are unclear, a candidate
  requires a new execution assumption, train/holdout boundaries change, or the same validation
  scenario fails twice. Anthropic allocations are advisory unless the user explicitly switches to
  an Anthropic-capable session.

## Checkpoint

Change `crypto-strategy-research-program` is at the proposal stage. This proposal is complete; the
next ready artifacts are `design` and `specs`. No implementation has begun. A replacement model
must run `openspec status --change crypto-strategy-research-program --json`, read this proposal and
the three dependency changes named above, then continue with the next ready artifact rather than
regenerating this file.
