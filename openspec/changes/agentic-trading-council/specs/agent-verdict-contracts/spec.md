## ADDED Requirements

### Requirement: Immutable as-of evidence bundle
The system SHALL freeze one content-addressed evidence bundle for each council run. Every included observation MUST have stable source provenance and an availability timestamp no later than the candidate's decision timestamp.

#### Scenario: Later information is present in storage
- **WHEN** storage contains an observation whose `available_at` is after `decision_ts`
- **THEN** evidence assembly excludes it from the bundle and records the exclusion reason

#### Scenario: Evidence changes during review
- **WHEN** new eligible evidence arrives after a council has started
- **THEN** the running council keeps its original bundle and a coordinator must create a new bundle version and council run to use the new evidence

### Requirement: Domain-complete evidence identity
An evidence bundle MUST identify domain, instrument, strategy and policy versions, market and source timestamps, provenance and freshness, quote and liquidity state, portfolio snapshot, contract or settlement rules, and explicit missing or conflicting fields required by its profile.

#### Scenario: Sports rules are missing
- **WHEN** a sports candidate has market evidence but no verified rule provenance
- **THEN** the bundle marks rules missing and the rules/settlement role cannot return support

### Requirement: Typed role verdict artifact
Every role result SHALL be parsed into a versioned `AgentVerdictArtifact` containing council run ID, role, specialization, schema/prompt/agent/model versions, `support|oppose|abstain|block`, confidence, severity and reason codes, evidence-linked claims, counterevidence, assumptions, unknowns, falsifiers, timing, usage, and parse status.

#### Scenario: Valid skeptic verdict
- **WHEN** the skeptic returns schema-valid objections linked to evidence IDs
- **THEN** the coordinator persists the parsed artifact and makes it eligible for deterministic policy

### Requirement: Evidence references and role permissions
The validator MUST reject unknown evidence IDs, temporally ineligible citations, out-of-range values, and actions a role is not permitted to propose. Free-text rationale MUST NOT substitute for required structured fields.

#### Scenario: Researcher proposes an order
- **WHEN** a non-voting researcher artifact includes a trade action or requested size
- **THEN** artifact validation fails with a role-permission error

#### Scenario: Claim cites nonexistent evidence
- **WHEN** a verdict claim references an ID outside the frozen bundle
- **THEN** that artifact is invalid and cannot count toward quorum

### Requirement: Single format-repair retry
The system MAY retry an invalid model output once for format repair using the original output and exact schema errors. It MUST NOT invite new analysis or evidence in the repair call. A second invalid response SHALL become abstain for an advisory role or block for a critical role according to versioned policy.

#### Scenario: First output contains malformed JSON
- **WHEN** an agent's first response cannot be parsed
- **THEN** the coordinator records the failed attempt and sends one format-repair request

#### Scenario: Critical repair also fails
- **WHEN** the critical rules/settlement role's repair response remains invalid
- **THEN** the coordinator records a critical block and the council outcome is hold

### Requirement: Typed master decision artifact
The final artifact MUST contain `take|hold|reject`, selected side when applicable, maximum entry and size bounds, expiration, invalidation conditions, summary, supporting verdict IDs, dissenting verdict IDs, council policy version, and deterministic quorum/veto result.

#### Scenario: Hold due to uncertainty
- **WHEN** evidence is insufficient rather than affirmatively adverse
- **THEN** the final artifact records hold, names the unknowns, and omits executable size

### Requirement: Append-only artifact lineage
Candidate envelopes, evidence bundles, agent definitions, attempts, verdicts, and final decisions SHALL be append-only and linked by stable identifiers and hashes. Retries, revisions, replays, and model switches MUST create new records rather than overwrite earlier artifacts.

#### Scenario: Agent switches models after timeout
- **WHEN** policy retries a role with a fallback model
- **THEN** both attempts remain linked to the same evidence bundle with distinct model and attempt identifiers

### Requirement: Minimal and redacted remote projection
The coordinator MUST send each agent only the fields required by its role. It MUST exclude credentials, broker clients, database access, unrelated portfolio data, and production-order identifiers from all agent inputs and raw-output logs.

#### Scenario: A2A execution role is invoked
- **WHEN** the coordinator builds the remote execution/liquidity task
- **THEN** it includes market observations and limits but no credential or order-mutating capability

## Model Complexity

Schema validation, citation existence, timestamp checks, permissions, lineage, and redaction are deterministic Python work. Evidence summarization and thesis artifacts are medium-to-high complexity, while format repair is low-to-medium. Proposal-time starts are GPT-5.6 Terra or GPT-6 Astra for synthesis and GPT-5.6 Luna for narrow repair; advisory Anthropic equivalents are Claude Sonnet 5 or Claude Opus 5 and Claude Haiku 4.5. Claude Fable 5.1 is reserved for eval-proven hard synthesis. These Anthropic allocations are advisory because no Anthropic subagent is available in this session.
