## Why

The sports feasibility pipeline now captures causal Kalshi prices, books, and
public trades, but it does not yet test whether anonymous order flow or dated
external evidence adds information beyond the market baseline. Named-trader
copying is not available from Kalshi's public feed, so the next useful step is
to study measurable flow proxies and auditable evidence without creating an
autonomous web-to-order path.

## What Changes

- Add research-only anonymous-flow features: aggressive trade imbalance,
  notional flow, book imbalance, quote replenishment, spread/depth changes,
  and post-flow price response.
- Add event-time and time-to-game stratification so flow signals are compared
  against the contemporaneous Kalshi probability and not mistaken for a
  named-trader edge.
- Add an evidence-card contract for optional lineup, injury, official game
  state, and approved consensus observations, retaining provider, URL,
  publication/observed time, availability time, retrieval time, and raw hash.
- Add a slow-path LLM research interface: local Ollama for structured review of
  already captured evidence, and opt-in OpenRouter for dated web retrieval and
  daily/weekly research briefs.
- Require domain allowlists, citation/provenance, prompt/output persistence,
  and temporal-leakage checks for all LLM-assisted evidence.
- Keep all LLM output advisory: it may summarize, classify, or veto a
  strategy-produced candidate, but it cannot originate, size, or place a
  sports order.
- Explicitly reject named-trader copy trading on Kalshi unless a future
  approved venue exposes lawful, attributable public positions.

## Capabilities

### New Capabilities

- `sports-flow-research`: derive and evaluate anonymous order-flow and
  microstructure features from captured Kalshi observations.
- `sports-evidence-provenance`: import optional external sports evidence with
  causal timestamps, source attribution, allowlists, and replayable hashes.
- `sports-llm-research`: provide local/OpenRouter structured research and
  review adapters with fail-closed boundaries and no order authority.

### Modified Capabilities

- `sports-market-data`: extend captured observations and joins with flow
  feature inputs and evidence-card identifiers; no change to the foreground,
  read-only collection requirement.
- `sports-feasibility-validation`: include flow/evidence candidates in the
  same chronological holdout, cost-adjusted fill, calibration, and
  promote-or-park evaluation.

## Impact

- Affected code: additive sports feature/evidence/LLM modules, storage models,
  validation reports, operator configuration, and tests.
- Kalshi remains the required market-data source. Any external provider is
  opt-in, must be separately approved, and must satisfy its terms and rate
  limits; no provider is selected by this proposal.
- OpenRouter/Ollama calls are research or review paths only. They cannot call
  order-placement APIs, change risk limits, or bypass the sports holdout gate.
- No paper/live sports execution, background scheduler, or named-trader
  copy-trading capability is introduced.
