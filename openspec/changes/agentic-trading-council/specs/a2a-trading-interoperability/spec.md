## ADDED Requirements

### Requirement: Transport-independent agent client
Trading-domain code SHALL depend on a transport-neutral agent client contract rather than A2A protocol objects. The system MUST provide an in-process implementation before or alongside the A2A implementation.

#### Scenario: Transport changes
- **WHEN** an operator changes a role from in-process to A2A transport
- **THEN** the candidate, evidence, verdict, quorum, and admission contracts remain unchanged

### Requirement: Pinned A2A protocol version
The A2A adapter MUST implement and request protocol version 1.0, MUST record the negotiated version on each task, and MUST reject an unsupported version or silent fallback.

#### Scenario: Remote server offers only an older version
- **WHEN** the configured agent cannot process A2A 1.0
- **THEN** capability validation fails and the criticality policy converts the role to abstain or block without retrying under an older protocol

### Requirement: Validated Agent Card discovery
Before enabling a remote agent, the system MUST retrieve its Agent Card from an allowlisted HTTPS location; validate its identity, interfaces, declared skills, input/output media types, capabilities, and security schemes; verify a configured signature requirement where applicable; and persist the accepted card hash and snapshot.

#### Scenario: Skill is not declared
- **WHEN** an Agent Card does not declare the council skill assigned to that endpoint
- **THEN** the profile is refused before any market evidence is sent

#### Scenario: Agent Card changes
- **WHEN** a previously accepted Agent Card hash changes
- **THEN** the system requires revalidation and records a new snapshot before using it

### Requirement: Restricted endpoint and authentication handling
A2A endpoints and redirects MUST remain within configured host/network allowlists. Authentication secrets MUST be resolved outside Agent Cards and MUST NOT be included in evidence bundles, artifacts, task history, or logs.

#### Scenario: Endpoint redirects to an unapproved host
- **WHEN** Agent Card or task transport redirects to a host outside the allowlist
- **THEN** the request is refused and a security failure is audited

### Requirement: A2A tasks produce typed artifacts
Each role invocation SHALL be a separate A2A Task linked to the council run. Critical results MUST be returned as Artifacts with the configured media type and verdict schema version; Messages and streaming status updates MUST NOT be treated as durable decision output.

#### Scenario: Agent sends recommendation only as a status message
- **WHEN** a task reaches a terminal state without the required verdict Artifact
- **THEN** the role is incomplete and cannot count toward quorum

### Requirement: Idempotent lifecycle and ordered updates
The coordinator MUST identify an invocation by council run, role, attempt, and request hash; process duplicate task or push updates idempotently; reject task-ID mismatches; and preserve event order for audit.

#### Scenario: Push notification is delivered twice
- **WHEN** the coordinator receives the same artifact update twice
- **THEN** it persists one logical artifact and records duplicate delivery without running policy twice

### Requirement: Deadlines, cancellation, and bounded retry
The A2A client MUST enforce connect, request, stream, and total role deadlines; bounded response sizes; cancellation; and the council's retry budget. A disconnected stream MUST be recoverable through task status retrieval without assuming transient Messages were durable.

#### Scenario: Remote task exceeds deadline
- **WHEN** a remote agent remains working past its role deadline
- **THEN** the coordinator requests cancellation, records timeout state, and applies criticality policy

### Requirement: No execution authority
An A2A trading agent MUST NOT receive production or paper broker mutation tools, venue credentials, or authority to change lifecycle, policy, bankroll, or risk state. Remote output SHALL remain advisory data until deterministic coordinator and adapter checks complete.

#### Scenario: Remote agent requests an order tool
- **WHEN** an A2A agent asks for or declares a skill that mutates orders
- **THEN** the coordinator refuses the request and records a capability-policy violation

### Requirement: Conformance and local fallback
The implementation MUST include recorded A2A 1.0 conformance fixtures covering discovery, task completion, failure, cancellation, duplicate updates, malformed artifacts, version mismatch, and authentication failure. An operator MUST be able to disable remote transport and return a profile to in-process or shadow-only behavior without deleting audit history.

#### Scenario: A2A dependency is unavailable
- **WHEN** remote transport is disabled or fails startup conformance
- **THEN** no remote task starts and configured in-process/shadow fallback behavior applies explicitly

## Model Complexity

A2A discovery, authentication, versioning, idempotency, timeout, conformance, and artifact validation are deterministic engineering tasks and require no model choice. Agents reached through A2A follow their council role allocations: GPT-6 Astra for high-complexity master/research, GPT-5.6 Terra for specialists, and GPT-5.6 Luna for narrow extraction; Anthropic advisory alternatives are Claude Fable 5.1/Opus 5, Sonnet 5, and Haiku 4.5. No Anthropic subagent is present, so cross-provider behavior MUST be established with conformance and domain evals during implementation.
