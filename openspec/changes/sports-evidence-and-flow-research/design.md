## Context

The preceding sports feasibility change provides read-only Kalshi candles,
order books, public trades, rule provenance, and chronological evaluation. Its
public-trade records contain no trader identity, so named-trader copying cannot
be implemented honestly. This change adds two bounded research inputs: derived
anonymous flow features and optional, attributable external evidence reviewed
by local or hosted models.

## Goals / Non-Goals

**Goals:**

- Measure whether anonymous flow predicts short-horizon repricing after fees,
  spread, depth, and partial fills.
- Preserve source and time provenance for lineup, injury, official game-state,
  and approved consensus observations.
- Make local Ollama the default structured reviewer and OpenRouter an opt-in
  slow-path web research provider.
- Persist prompts, retrieved evidence, model identity, citations, and outputs
  so the result can be audited and replayed.

**Non-Goals:**

- Identifying, ranking, or copying Kalshi users.
- Letting an LLM originate a signal, choose a market, size a position, or
  place an order.
- Retrospective web searches, unbounded scraping, or an unattended collector.
- Adding a paid provider or enabling sports paper/live execution.

## Decisions

### D1 — Anonymous flow, not copy trading

Compute signed trade imbalance, notional flow, book imbalance, quote
replenishment, spread/depth changes, and subsequent price response from the
captured Kalshi observations. Public trades are anonymous, so identity-based
copying is recorded as unsupported. This is preferred to inferring identities
from trade patterns, which is fragile and creates privacy and leakage risks.

### D2 — Evidence cards are immutable inputs

External observations use an adapter contract with provider, endpoint or URL,
publication/observed time, local availability time, retrieval time, raw
content hash, and extracted claims. Cards are append-only and linked to a
market/session. Missing or conflicting evidence is explicit; it is never
filled or silently resolved.

### D3 — Separate retrieval from interpretation

OpenRouter may perform slow, opt-in web retrieval with an allowlist and return
cited evidence cards or a daily/weekly brief. Ollama receives only the
structured cards and market snapshot for local classification/review. The
strategy remains the sole signal origin, and the existing fail-closed veto is
the only model output allowed near a future trade path.

Alternative considered: direct LLM web-to-order decisions. Rejected because
search results can contain future information, provider output is not a
deterministic market model, and the existing sports gate requires causal,
holdout-safe inputs.

### D4 — One evaluation harness

Flow-only, evidence-only, combined, and market-baseline candidates use the
same chronological split, time-to-event buckets, calibration metrics,
execution simulator, concentration, and drawdown report. Feature transforms
and evidence filters fit only on prior data; holdout access is a hard error.

## Risks / Trade-offs

- **[Anonymous flow is mostly noise]** → Require incremental predictive value
  over the market baseline and park on insufficient holdout evidence.
- **[News is stale or published after the decision]** → Enforce observed and
  available timestamps plus a point-in-time eligibility check.
- **[LLM hallucinates or misquotes a source]** → Persist raw excerpts/hashes,
  citations, structured schemas, and fail closed on malformed output.
- **[External provider cost/terms change]** → Keep adapters opt-in, allowlisted,
  rate-limited, and disabled by default; no provider is selected here.
- **[Flow features leak future book state]** → Build features only from rows
  whose availability precedes the simulated decision time.

## Migration Plan

1. Add additive feature/evidence/LLM records and indexes; do not rewrite
   existing sports or crypto rows.
2. Run anonymous-flow evaluation using existing Kalshi captures first.
3. Add an approved evidence adapter only after its terms and domain allowlist
   are recorded; run it in foreground research sessions.
4. Benchmark local Ollama and optional OpenRouter on frozen prompts, then run
   combined holdout reports.
5. Rollback is disabling the optional adapters and research commands; no
   order path depends on this change.

## Open Questions

- Which official or licensed source, if any, should be approved for the first
  evidence adapter?
- What minimum flow sample and effect size justify a second pilot?
- Should a future paper-trading proposal consume flow features, evidence
  cards, or only a validated combination?
