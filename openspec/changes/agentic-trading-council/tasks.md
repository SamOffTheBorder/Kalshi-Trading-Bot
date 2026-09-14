## 1. Contracts and profile configuration

- [x] 1.1 Add `src/kalshi_bot/agents/` with typed domain, specialization, candidate, evidence, verdict, decision, policy, and lifecycle contracts matching all five capability specs.
- [x] 1.2 Add hierarchical council-profile configuration for prediction asset/cadence, perp asset/strategy class, and sports sport/league/market class, including inheritance and strict validation.
- [x] 1.3 Define role permissions and criticality for researcher, bull, bear, skeptic, execution/liquidity, rules/settlement, portfolio risk, and master synthesis.
- [x] 1.4 Add per-role and council-total deadlines, token/cost ceilings, response-size ceilings, retry limits, and concurrency limits with conservative defaults.
- [x] 1.5 Add profile model routing with proposal-time starts: GPT-6 Astra for high-complexity master/research, GPT-5.6 Terra for medium/high specialist work, and GPT-5.6 Luna for narrow extraction/repair; keep deterministic checks model-free.
- [x] 1.6 Add advisory Anthropic profile examples for Claude Fable 5.1/Opus 5, Sonnet 5, and Haiku 4.5, explicitly disabled until an Anthropic integration and evals exist because no Anthropic subagent was available during planning.
- [x] 1.7 Unit-test unknown roles, incompatible specialization keys, missing critical roles, invalid budgets, unsupported model/provider settings, and invalid lifecycle transitions.

## 2. Append-only storage and migrations

- [x] 2.1 Add additive storage models and migrations for council runs, immutable evidence bundles, agent-definition snapshots, verdict attempts, and council decisions.
- [x] 2.2 Add uniqueness and foreign-key constraints for candidate/evidence lineage and idempotent `(council_run_id, role, attempt, request_hash)` handling.
- [x] 2.3 Add council and decision reference fields or linked records for existing `PaperRun`/`PaperAuditEvent` traces without rewriting old rows.
- [x] 2.4 Implement repository functions that append attempts, revisions, replay links, and final decisions while refusing mutation of sealed artifacts.
- [x] 2.5 Implement raw-output redaction/encryption policy and retain hashes, parsed artifacts, usage, and failure metadata for audit.
- [x] 2.6 Test migration on an existing populated database, idempotent re-run, rollback compatibility, append-only enforcement, and old paper-event readability.

## 3. Candidate and evidence assembly

- [x] 3.1 Implement domain-neutral `TradeCandidateEnvelope` adapters for prediction, perpetual, and sports strategy/finder outputs without adding broker actions.
- [x] 3.2 Implement immutable point-in-time evidence assembly that enforces `available_at <= decision_ts`, stable IDs, source provenance, hashes, and exclusion reasons.
- [x] 3.3 Add prediction evidence projection for asset/cadence, contract identity, settlement window, BRTI/spot inputs, quotes/depth, strategy features, and manifest/freshness state.
- [x] 3.4 Add perpetual evidence projection for asset, strategy class, mark, bid/ask, depth, funding, multiplier, margin/liquidation, discovery, and hedge/basis fields where applicable.
- [x] 3.5 Add sports evidence projection for sport/league/market class, verified rules, event identity, provider evidence, conflicts, odds/flow, quote liquidity, and feasibility state.
- [x] 3.6 Add role-specific minimal projections that exclude credentials, broker/client objects, unrelated portfolio details, production identifiers, and unauthorized fields.
- [x] 3.7 Test temporal cutoff, missing/conflicting evidence, bundle immutability, hash stability, cross-domain field isolation, and malicious source-text treatment.

## 4. Verdict schemas and model gateway

- [x] 4.1 Implement strict structured schemas for role verdicts and master decisions, including evidence-linked claims, counterevidence, assumptions, unknowns, falsifiers, dissent, bounds, usage, and version metadata.
- [x] 4.2 Implement deterministic validation of evidence IDs, temporal eligibility, enum/range constraints, confidence, role permissions, and authorized price/size fields.
- [x] 4.3 Implement one format-repair retry using only the original output and exact schema errors, with advisory abstain and critical block behavior after exhaustion.
- [x] 4.4 Implement a provider-neutral in-process agent client and model gateway with deterministic request hashes, deadlines, usage capture, cancellation, and resumable attempts.
- [x] 4.5 Wrap the existing `LocalReviewClient` as a compatible in-process skeptic/risk-review role while preserving fail-closed behavior and legacy audit linkage.
- [x] 4.6 Adapt sports research summarization to produce a non-voting evidence-linked researcher artifact and preserve its prohibition on proposing trades.
- [x] 4.7 Add prompts for every role that define mandates rather than personalities, require abstention on missing evidence, and forbid uncited facts and hidden gate overrides.
- [x] 4.8 Test malformed JSON, schema drift, fabricated evidence citations, unauthorized order proposals, provider errors, timeouts, model fallback, and raw-output preservation.

## 5. Council coordinator and deterministic policy

- [x] 5.1 Implement hierarchical profile routing and refuse candidates with no compatible enabled specialist.
- [x] 5.2 Implement blind concurrent first-round execution with shared evidence hash, bounded worker pool, deterministic role ordering in persisted results, and cancellation on total budget/deadline.
- [x] 5.3 Implement versioned deterministic quorum, critical-role completion, abstention, veto, and reason-code policy.
- [x] 5.4 Implement one optional critique/revision round using validated anonymized claims and evidence IDs, with no third round and no uncaptured facts.
- [x] 5.5 Implement constrained master synthesis over validated artifacts and policy output, including take/hold/reject, dissent, invalidation, expiry, and price/size ceilings.
- [x] 5.6 Persist a checkpoint after each evidence, role, revision, policy, and master step so a model switch or interrupted run resumes without hidden conversation state.
- [x] 5.7 Test blind-review isolation, deterministic results under completion-order changes, critical failure, budget exhaustion, unresolved disagreement, invalid master evidence, and resume behavior.

## 6. Deterministic admission and paper integration

- [x] 6.1 Add a cheap pre-council screen using existing lifecycle, manifest/provenance, quality, freshness, market-state, domain-admission, emergency, and paper-safety checks.
- [x] 6.2 Integrate councils at the candidate-to-adapter boundary so only existing domain adapters can create simulated orders.
- [x] 6.3 Add the post-council freshness, quote, emergency, bankroll, leverage, concentration, drawdown, risk, and domain-admission recheck.
- [x] 6.4 Implement `shadow` behavior that records counterfactual council output without changing existing paper decisions or fills.
- [x] 6.5 Implement `paper_advisory` monotonic influence: hold or tighten price/size only, never originate direction, enlarge risk, loosen price, or revive a refused candidate.
- [x] 6.6 Refuse live council configuration and verify agent constructors receive no live or paper broker mutation surface.
- [x] 6.7 Link initial screen, council recommendation, final admission, adapter decision, and fill/refusal in append-only audit output.
- [x] 6.8 Add prediction, perp, and sports integration tests proving every deterministic refusal wins over unanimous/model-master support and that quote expiry during review blocks fills.

## 7. A2A 1.0 interoperability

- [x] 7.1 Pin the official A2A 1.0 SDK/protocol dependency and record the exact package/version and conformance source in dependency metadata.
- [x] 7.2 Implement the transport-neutral `AgentClient` port for capability discovery, submit, status, cancel, and artifact retrieval.
- [x] 7.3 Implement A2A 1.0 Agent Card retrieval over HTTPS with host/network allowlists, redirect restrictions, interface/skill/media/security validation, optional signature policy, and accepted-card snapshots.
- [x] 7.4 Implement A2A task submission with explicit `A2A-Version: 1.0`, council context metadata, idempotency key, authentication resolved outside cards/logs, and strict no-downgrade behavior.
- [x] 7.5 Accept durable verdicts only from expected typed Artifacts; treat Messages and streaming status as informational and recover disconnected streams via task status.
- [x] 7.6 Implement ordered/idempotent update processing, task-ID validation, duplicate-delivery handling, response-size limits, deadlines, cancellation, and bounded retries.
- [x] 7.7 Reject remote skills or requests that imply order mutation, credentials, policy changes, lifecycle changes, or unsupported tools.
- [x] 7.8 Build local A2A conformance fixtures for card change, success, failure, cancellation, duplicate updates, malformed artifact, task mismatch, auth failure, timeout, and version mismatch.
- [x] 7.9 Add an operator switch that disables A2A and selects explicit in-process or shadow-only fallback without deleting council history.

## 8. Replay, metrics, and promotion governance

- [x] 8.1 Implement profile lifecycle storage and one-step explicit transitions for disabled, fixture, replay, shadow, paper_advisory, and paper_council, plus append-only demotion.
- [x] 8.2 Build an outcome-blind replay runner over frozen candidate/evidence snapshots and join realized outcomes only after decisions are sealed.
- [x] 8.3 Implement no-agent and single-agent baselines over the identical candidate set and execution assumptions.
- [x] 8.4 Compute artifact validity, timeout, abstention/hold, citation validity, calibration/Brier score where applicable, false approval/veto, net result after costs, drawdown, stability, disagreement/error correlation, latency, and model cost metrics.
- [x] 8.5 Implement pre-registration and freezing of windows, samples, thresholds, manifests, profile/policy/prompts/models, code revision, seeds, and execution assumptions before held-out scoring.
- [x] 8.6 Implement profile-specific worst-component promotion reports that cannot hide a failing asset, sport, role, or market class behind aggregate results.
- [x] 8.7 Add champion/challenger comparisons for economical versus strong models and same-provider versus cross-provider diversity, measuring correlated errors instead of assuming independence.
- [x] 8.8 Test outcome leakage refusal, late threshold registration, non-positive net incremental value, component failure, explicit promotion, one-step advancement, and rollback to shadow.

## 9. BTC 15-minute shadow pilot

- [x] 9.1 Create a conservative `prediction/BTC/15m` profile with all required roles, deterministic policy, model/cost/latency budgets, and council lifecycle set no higher than fixture.
- [x] 9.2 Build representative BTC fixtures covering take, reject, insufficient evidence, stale quote, settlement ambiguity, bull/bear conflict, prompt injection, timeout, and risk refusal.
- [x] 9.3 Run fixture and outcome-blind replay suites, freeze their reports, and resolve all schema, temporal, audit, and deterministic-authority failures.
- [x] 9.4 Promote only the BTC profile to shadow with explicit operator evidence and run it beside the current BTC 15-minute decision path.
- [x] 9.5 Produce a frozen shadow report comparing council, single-agent, and no-agent baselines with disagreement, cost, latency, and counterfactual fill impact.
- [x] 9.6 Keep BTC in shadow unless every pre-registered threshold passes; if it passes, require a separate explicit task/operator transition before `paper_advisory`.

## 10. Operator visibility and documentation

- [x] 10.1 Add CLI inspection for council profiles, lifecycle, latest run, role status, veto/quorum result, cost/latency, deterministic final admission, and replay links.
- [x] 10.2 Add dashboard views from a paper run/candidate to the evidence bundle, each role artifact, dissent, master result, and final deterministic gate.
- [x] 10.3 Surface disabled/missing A2A cards, version mismatches, timeouts, budget exhaustion, malformed artifacts, and profile promotion blockers without exposing secrets or raw unsafe content.
- [x] 10.4 Document council concepts, role mandates, profile inheritance, A2A configuration/security, budgets, shadow operation, promotion/demotion, audit queries, and emergency behavior.
- [x] 10.5 Document that a council is advisory, cannot promote itself, cannot bypass deterministic gates, and cannot place live orders.

## 11. Perpetual and sports follow-on profiles

- [x] 11.1 Verify a real directional perp strategy, fresh mark/funding/discovery data, margin/liquidation semantics, and existing admission are operational before enabling a BTC perp profile beyond fixture/replay.
- [x] 11.2 Create and evaluate separate BTC directional-perp and funding-carry profiles so two-leg carry evidence and risk are not conflated with direction.
- [x] 11.3 Select one sports sport/league/market class only after a qualifying feasibility report, verified rules, provider evidence, fresh liquid observations, and operator acknowledgment exist.
- [x] 11.4 Create and evaluate the selected sports profile with sport/league-specific evidence, settlement, liquidity, conflict, and information-timing fixtures.
- [x] 11.5 Require independent frozen reports and explicit promotions for each additional crypto asset, cadence, sport, league, or market class.

## 12. Final verification

- [x] 12.1 Run focused unit and integration suites for contracts, storage, evidence, verdicts, coordinator, admission, A2A, replay, CLI, and dashboard.
- [x] 12.2 Run the full test suite and static/type/lint checks configured by the repository, recording unrelated pre-existing failures separately.
- [x] 12.3 Run OpenSpec strict validation and confirm proposal capabilities, specs, design decisions, and every tracked task remain aligned.
- [x] 12.4 Perform a paper-safety review proving no new live-order import or credential path reaches any agent, coordinator, A2A server, or council profile.
- [x] 12.5 Record the final model-complexity benchmark and chosen per-role configuration; Anthropic choices remain advisory unless actually exercised through an available integration.
