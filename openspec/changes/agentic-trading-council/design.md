## Context

The repository already separates deterministic strategies, domain paper adapters, lifecycle admission, paper safety, portfolio governance, and append-only audit events. It also has two narrow AI paths: `LocalReviewClient`, a fail-closed single-model veto over a small prediction candidate, and `sports_research`, which summarizes only captured point-in-time evidence and is forbidden to propose trades. There is no common multi-agent contract, no independent bull/bear review, no specialist routing, and no measured way to determine whether extra agents improve decisions.

LarpQuest supplies the useful control pattern: generation and validation are different roles; validators consume a frozen candidate; outputs are schema checked; findings have explicit severities; retries are capped; and unresolved failures escalate instead of looping indefinitely. Trading requires a stricter adaptation. A model failure, missing evidence, or unresolved dispute must become `hold`; an operator or master agent cannot override deterministic safety and admission requirements.

The stakeholders are the local operator, strategy/research authors, paper-run reviewers, and future agent-service maintainers. The design must work locally with in-process agents, remain reproducible in backtests/replay, and permit later A2A deployment without changing the trading-domain contracts.

## Goals / Non-Goals

**Goals:**

- Route prediction, perpetual, and sports candidates to domain and instrument specialists.
- Obtain genuinely independent evidence-linked perspectives before synthesis.
- Make every input, verdict, dissent, model call, and final gate outcome replayable and auditable.
- Keep hard data, execution, lifecycle, bankroll, and paper-safety policy authoritative.
- Support an in-process transport first and A2A 1.0 agents behind the same typed interface.
- Prove incremental value in shadow mode before any council output can influence a paper fill.

**Non-Goals:**

- Allowing an LLM or remote agent to place, amend, or cancel any order.
- Enabling live trading, relaxing current admission gates, or promoting lifecycle state.
- Treating role names or different prompts as proof of independent judgment.
- Giving every symbol or sport a permanent process in the first release.
- Letting agents browse freely during a decision or use information captured after `decision_ts`.
- Replacing quantitative strategies, forecasts, market data, or deterministic risk policy with debate.

## Decisions

### 1. A council reviews a candidate; it does not originate broker actions

The domain adapter or finder creates a normalized `TradeCandidateEnvelope` from its existing strategy output. The envelope identifies domain, instrument, strategy, decision timestamp, proposed action, price/size bounds, horizon, settlement or contract definition, and evidence manifest. The council returns a `CouncilDecisionArtifact`; only the existing adapter may translate an admitted decision into a simulated order.

The execution order is:

1. Run cheap deterministic eligibility checks and stop before model calls when lifecycle, source provenance, freshness, market state, or paper safety already blocks the candidate.
2. Freeze an as-of evidence bundle and its hash.
3. Run independent council roles concurrently.
4. Apply deterministic quorum and veto policy.
5. If eligible, run one bounded critique/revision round and master synthesis.
6. Re-run time-sensitive deterministic checks, portfolio risk, and adapter-specific admission immediately before a possible paper fill.
7. Persist the recommendation and every gate result whether the outcome is `take`, `hold`, or `reject`.

This places expensive reasoning between two deterministic walls. The second wall handles quotes or portfolio state that changed while agents ran.

**Alternative considered:** let a master agent scan markets and execute its own ideas. Rejected because it combines proposal, approval, and action in one opaque path and bypasses the repository's strategy and admission contracts.

### 2. Specialization is hierarchical configuration, not one daemon per market

The router selects a `CouncilProfile` by domain and specialization key:

- Prediction: `prediction/<asset>/<cadence-or-contract-class>`, initially `prediction/BTC/15m`.
- Perpetual: `perp/<asset>/<strategy-class>`, initially `perp/BTC/directional`; funding carry uses a distinct profile because it has two-leg and funding semantics.
- Sports: `sports/<sport>/<league>/<market-class>`, beginning only with a sport/league already admitted by sports feasibility research.

Profiles inherit role templates and policy from the domain, then add instrument vocabulary, allowed evidence types, and settlement/execution checks. A new asset or sport is a versioned configuration plus eval suite, not copied orchestration code. The worker pool is shared and bounded; logical specialists are instantiated per task.

**Alternative considered:** launch a long-lived process for every crypto and sport. Deferred because it creates idle cost, state drift, and operational complexity before workload or measured specialization benefit justifies it.

### 3. Roles have distinct mandates, evidence obligations, and voting authority

Each first-round role receives the same immutable evidence bundle and cannot see another role's verdict:

| Role | Mandate | Vote / veto |
|---|---|---|
| Researcher | Summarize current captured conditions, conflicts, and unknowns with evidence IDs | Non-voting; may mark evidence insufficient |
| Bull thesis | Construct the strongest evidence-supported case for the proposed positive/long side | Directional vote; may abstain |
| Bear thesis | Construct the strongest evidence-supported case for the negative/short side | Directional vote; may abstain |
| Skeptic / red team | Find leakage, stale facts, unsupported assumptions, correlated reasoning, and falsifiers | Objection; policy-class evidence faults may veto |
| Execution / liquidity | Assess executable price, spread, depth, fees, slippage, horizon, and exit feasibility | Hard veto on deterministic execution failures; advisory otherwise |
| Rules / settlement | Check instrument identity, event wording, resolution source, deadlines, and side semantics | Hard veto on unknown or conflicting rules |
| Portfolio risk | Assess exposure, concentration, correlation group, drawdown, and scenario loss | Hard veto through deterministic risk results; narrative is advisory |
| Master synthesizer | Explain the aggregate result, resolve supported claims, preserve dissent, and propose bounds | Cannot erase vetoes, invent evidence, or change policy |

“Bullish,” “bearish,” and “skeptical” are mandates, not personalities. Their prompts require claims, counterevidence, falsifiers, and abstention when evidence is absent. Different providers or model families may be used to reduce correlated errors, but independence is measured by disagreement and error correlation rather than assumed from model labels.

**Alternative considered:** majority vote among several chat personas. Rejected because correlated prompts can create false consensus, majority voting cannot validate market mechanics, and it gives weak opinions the same weight as settlement or safety failures.

### 4. Immutable evidence and strict verdict schemas are the trust boundary

`EvidenceBundle` is assembled at one `decision_ts` and contains only persisted or freshly captured records whose `available_at <= decision_ts`. It includes stable evidence IDs and hashes, source provenance, observation times, freshness state, market quotes/depth, strategy features, domain rules, portfolio snapshot, and explicit missing/conflicting fields. Remote agents receive the minimum role-specific projection plus the bundle hash; raw credentials, database handles, broker clients, and unrestricted tools are never supplied.

Every role returns an `AgentVerdictArtifact` with:

- council run, role, domain, specialization, schema, prompt, agent, model, and evidence-bundle versions;
- `support | oppose | abstain | block`, confidence, severity, and reason codes;
- claims linked to evidence IDs, counterevidence, assumptions, unknowns, and falsifiers;
- proposed action/price/size bounds only where the role is authorized;
- latency, token/cost usage, A2A task metadata, raw-output hash, and parse status.

Free-text rationale is supplemental. The coordinator validates identifiers, enum values, bounds, evidence citations, temporal eligibility, and role permissions. One format-repair retry may receive only the schema error and original response. A second parse failure produces an abstention or block according to role criticality; it never becomes approval.

The master receives validated artifacts, not hidden reasoning or raw chains of thought. It returns `take | hold | reject`, selected side, maximum entry and size, expiry, invalidation conditions, summary, supporting verdict IDs, dissent IDs, and policy result. It cannot cite evidence absent from the bundle.

**Alternative considered:** pass a growing shared conversation among agents. Rejected because it causes anchoring, makes replay order-dependent, leaks untrusted content across roles, and obscures which agent supplied a claim.

### 5. Deterministic policy controls quorum, vetoes, retries, and final authority

`CouncilPolicy` is versioned by domain/profile. The initial conservative policy requires all critical roles to return valid artifacts, at least one bull and one bear verdict, no unresolved settlement/execution/data-integrity block, and no risk-policy refusal. Missing critical roles, deadline expiry, unsupported evidence, or conflicting instrument identity results in `hold`.

The council may run one reconsideration round when there is a resolvable evidence request or a material thesis conflict. The coordinator supplies each revising agent with the validated opposing claims and evidence IDs, not agent identity or private reasoning. No new external facts may enter unless the coordinator captures them as a new immutable evidence-bundle version and starts a new council run. There is no third round.

The master can choose `reject` when evidence affirmatively defeats the candidate and `hold` when uncertainty, failure, or temporary conditions prevent action. A `take` is only a recommendation. Existing lifecycle, manifest, freshness, domain admission, emergency halt, bankroll, leverage, concentration, and paper guard checks have final veto power. Council output cannot move a scope from observe/backtest/shadow to paper.

**Alternative considered:** let the master dynamically weight and override all roles. Rejected because weights would be unaudited policy hidden inside a probabilistic response.

### 6. One internal agent port supports local calls and A2A 1.0

The domain layer depends on an `AgentClient` port with operations to inspect a capability descriptor, submit a task with an idempotency key and deadline, obtain status, cancel, and retrieve typed artifacts. Two adapters implement it:

- `InProcessAgentClient` invokes configured model/provider gateways locally and is the first implementation.
- `A2AAgentClient` maps the same request to A2A 1.0 Agent Cards, Messages, Tasks, and Artifacts.

A2A is pinned to protocol major/minor `1.0`; every request sends the version and rejects silent downgrade. Startup fetches configured Agent Cards from an allowlist, validates declared skills, interfaces, security schemes, and optional signatures, then snapshots and hashes the accepted card. Endpoint redirects, private-network reachability, and host changes are rejected unless explicitly allowlisted. Authentication is stored outside Agent Cards and logs.

Each council role invocation is a separate A2A task with the council run as context metadata. Critical output is accepted only as an Artifact carrying the expected media type and schema version; status Messages and streaming events are informational. Duplicate delivery is handled idempotently by `(council_run_id, role, attempt, request_hash)`. Deadlines, cancellation, retry budgets, response size, and concurrency are enforced by the coordinator. A remote agent never receives an execution tool or production credential.

**Alternative considered:** make internal Python objects mirror A2A protobuf types. Rejected because protocol upgrades would leak transport churn throughout strategy and execution code.

### 7. Append-only persistence makes council decisions replayable

Add additive storage for:

- `CouncilRunRecord`: candidate/evidence hashes, domain/profile, policy version, state, timing, parent replay/run IDs.
- `EvidenceBundleRecord`: immutable manifest and serialized point-in-time references.
- `AgentDefinitionSnapshot`: accepted role configuration, prompt/model/provider, capability/card hash, and permissions.
- `AgentVerdictRecord`: validated artifact, raw-output hash, status, usage, and A2A identifiers.
- `CouncilDecisionRecord`: quorum/veto calculation, master artifact, dissent, final deterministic gate outcome, and linked paper decision/fill if any.

Rows are append-only. Retries and revisions create attempts; they do not mutate prior output. Raw provider responses may be encrypted or locally redacted, while hashes and parsed artifacts remain available for audit. Existing `PaperAuditEvent` receives council run/decision references so the operator can trace from a paper decision back to every artifact.

**Alternative considered:** store council details only inside the existing JSON event payload. Rejected because role-level evaluation, uniqueness, replay, and joins would be fragile.

### 8. Evaluation precedes influence on paper fills

Rollout has separate lifecycle controls for a council profile:

1. `fixture`: schema, temporal, failure, and adversarial prompt-injection tests.
2. `replay`: run over frozen historical candidate/evidence snapshots without access to outcomes.
3. `shadow`: run beside the current strategy and record recommendations without changing paper decisions.
4. `paper_advisory`: the council may convert a candidate to `hold` or tighten price/size, but cannot create a trade the base strategy rejected.
5. `paper_council`: the council may select among candidates already admitted by deterministic strategy and policy; still no live mode.

Promotion is explicit, profile-specific, and based on a frozen report. Metrics include artifact validity, deadline success, abstention and hold rates, evidence citation validity, calibration/Brier score where probabilistic forecasts are emitted, false approvals, false vetoes, realized net outcome after costs, drawdown, disagreement/error correlation, decision stability, incremental value over single-agent and no-agent baselines, latency, and cost per reviewed/taken candidate. Thresholds and evaluation windows are registered before held-out evaluation.

The first experiment is `prediction/BTC/15m` in shadow mode because it has the most mature strategy path. BTC perpetual follows only when mark, funding, discovery, and directional strategy gates are real. Sports follows only after a narrow sport/league/market class reaches the existing `research_promising` feasibility requirement.

**Alternative considered:** deploy all asset and sport specialists together. Rejected because failures could not be attributed and cost/latency would grow before incremental value is known.

### 9. Model assignment is role-based, versioned, and evaluated

The model matrix is configuration, never hardcoded at call sites. A proposal-time starting matrix is:

| Work | Complexity | OpenAI/Codex Pro start | Anthropic advisory alternative |
|---|---|---|---|
| Master synthesis, difficult cross-source research | High / very high | GPT-6 Astra | Claude Opus 5; escalate eval failures to Claude Fable 5.1 |
| Bull, bear, skeptic, rules, execution narrative | Medium / high | GPT-5.6 Terra | Claude Sonnet 5 |
| Routing, narrow extraction, format repair | Low / medium | GPT-5.6 Luna | Claude Haiku 4.5 |
| Temporal checks, citation existence, quorum, veto, sizing/risk gates | Deterministic | Python, no model | Python, no model |

Model diversity is a testable variant, not a requirement to pay for frontier models on every role. The default experiment uses economical specialists and a stronger master only after deterministic policy permits synthesis. Prompt caching and shared immutable prefixes should reduce repeated input cost where providers support them. Each profile has per-role and total deadlines, token ceilings, dollar ceilings, and concurrency limits.

The current session cannot execute Anthropic subagents, so Anthropic names are advisory. The implementation checkpoint is resumable: every completed artifact is committed to append-only storage before another model call, and a replacement model resumes from the evidence bundle plus validated artifacts rather than hidden conversational state.

## Risks / Trade-offs

- [Correlated hallucinations create false consensus] -> Blind first-round reviews, evidence-ID enforcement, model/provider diversity experiments, and measured error correlation.
- [More agents add confidence without predictive value] -> No paper influence until held-out replay and shadow comparisons beat registered baselines after fees and cost.
- [Agent latency makes quotes stale] -> Pre-screen, parallel role execution, strict deadlines, cancellation, and final freshness/execution recheck.
- [Cost grows linearly with candidates] -> Deterministic cheap filters first, profile budgets, shared evidence, smaller specialist models, and sample/rate caps.
- [Prompt injection enters through news or sports evidence] -> Treat all source text as untrusted data, restrict tools, cite captured evidence only, validate outputs, and deny agents credentials or execution capability.
- [Remote A2A agent or Agent Card is spoofed] -> TLS, allowlisted hosts, explicit auth, accepted-card snapshots/signatures where available, capability validation, and no silent protocol downgrade.
- [A2A standard or SDK changes] -> Pin A2A 1.0 and SDK versions, isolate transport adapters, preserve conformance fixtures, and upgrade as a separate change.
- [Master explanation hides dissent] -> Persist every verdict and require the master artifact to reference supporting and dissenting verdict IDs.
- [The council vetoes too often] -> Distinguish temporary `hold` from evidence-based `reject`, track false-veto rate, and adjust versioned policy only through new evals.
- [Sports and crypto specializations multiply configuration] -> Hierarchical profiles, shared role templates, typed overrides, and profile-specific promotion.
- [Agents accidentally become a route around existing gates] -> Dependency direction allows council output into admission only; broker and live clients are absent from agent constructors and A2A services.

## Migration Plan

1. Add typed envelopes, verdicts, policies, persistence, and deterministic coordinator tests without any provider calls.
2. Wrap the current local review behavior as one in-process role, preserving its fail-closed behavior while writing the new artifacts.
3. Build frozen evidence assembly and replay fixtures for BTC 15m; add temporal and prompt-injection tests.
4. Implement in-process research, bull, bear, skeptic, execution, rules, risk, and master roles with configurable models and budgets.
5. Run the BTC 15m council in `shadow`; expose audit, disagreement, cost, latency, and baseline comparison on CLI/dashboard.
6. Implement and conformance-test the A2A 1.0 adapter against local test agents. Keep in-process transport as rollback.
7. Promote BTC 15m to `paper_advisory` only with a signed/frozen evaluation report and explicit operator transition. Roll back by returning the council profile to `shadow`; current base paper behavior remains intact.
8. Add BTC perp and one qualified sports profile separately, each with domain-specific fixtures and promotion reports. Scale to other assets/sports only by configuration plus profile evals.

All migrations are additive. Disabling the council or selecting the in-process null/hold profile restores existing strategy/admission behavior; council records remain for audit. No rollback deletes rows or rewrites prior paper events.

## Open Questions

- What numerical quorum, confidence, latency, and cost thresholds should the first BTC 15m experiment register before its held-out run?
- Should the first diversity test compare model families, independent prompts on one model, or both? Recommendation: measure one economical same-model baseline first, then a two-provider challenger.
- Which hosted-provider credentials and data-retention terms are acceptable for market evidence? Until decided, remote agents receive redacted/minimal projections and remain disabled by default.
- Which exact perp directional strategy should create the first reviewable candidate? The current CLI path defaults to hold, so this must be resolved before a perp council can demonstrate value.
- Which sport, league, and market class will clear feasibility first? Do not pre-create paper-enabled profiles until that report exists.
- Should `paper_council` ever originate a direction from an otherwise neutral strategy? Recommendation: exclude this from the initial change and consider it only after advisory results demonstrate calibrated incremental value.
