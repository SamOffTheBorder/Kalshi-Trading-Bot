## 1. Anonymous flow feature foundation

- [x] 1.1 Add additive storage records for versioned flow features and feature-window provenance.
- [x] 1.2 Implement causal signed trade imbalance, notional flow, book imbalance, quote replenishment, spread/depth change, and post-flow response calculations.
- [x] 1.3 Add explicit `copy_trading_unsupported` handling when public observations contain no attributable trader identity.
- [x] 1.4 Add known-answer tests for feature calculations, empty books, partial depth, duplicate trades, and timestamp causality.

## 2. Evidence provenance and adapters

- [x] 2.1 Add append-only evidence-card storage with provider, endpoint/URL, claim, publication/observed time, availability time, retrieval time, raw hash, and version fields.
- [x] 2.2 Define an opt-in external-source adapter protocol with provider/domain allowlisting, rate limits, and no default provider.
- [x] 2.3 Implement temporal eligibility and conflict/version handling without interpolation or silent source replacement.
- [x] 2.4 Add fixture tests for missing timestamps, changed source content, disallowed domains, conflicting claims, and unconfigured adapters.

## 3. LLM research and review

- [x] 3.1 Define structured evidence-summary and review schemas with model identity, prompt hash, output hash, citations, latency, and availability status.
- [x] 3.2 Implement local Ollama structured review over captured evidence only; failures remain unavailable or fail-closed for veto use.
- [x] 3.3 Implement opt-in OpenRouter slow-path web research using the `openrouter:web_search` tool, domain filters, bounded result counts, and persisted citations.
- [x] 3.4 Enforce an AI capability boundary: no LLM-originated signals, position sizing, risk-limit changes, or order API access.
- [x] 3.5 Add mocked tests for local/hosted success, outage, malformed output, citation persistence, temporal leakage rejection, and strategy-signal-only review.

## 4. Combined evaluation and operator gate

- [x] 4.1 Extend sports feasibility inputs to evaluate market baseline, flow-only, evidence-only, and combined candidates under the same chronological holdout.
- [x] 4.2 Add report fields for feature/evidence/model versions, hashes, costs, calibration, executable fills, concentration, and drawdown.
- [x] 4.3 Add a foreground operator command for bounded evidence retrieval and flow-feature generation; prohibit scheduling, restart, and order placement.
- [x] 4.4 Pre-register the first flow/evidence pilot's series, allowlist, holdout boundary, thresholds, and minimum sample before holdout access.
- [ ] 4.5 Run the first complete combined report after sufficient data and record `research_promising`, `park`, or `insufficient_data`; keep sports execution disabled. (Blocked by current zero-row `sports_candles` capture; sports execution remains disabled.)
