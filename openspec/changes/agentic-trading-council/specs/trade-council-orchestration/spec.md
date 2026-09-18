## ADDED Requirements

### Requirement: Candidate-first council invocation
The system SHALL invoke a trade council only for a normalized candidate produced by an existing domain finder or strategy, and SHALL identify the candidate's domain, instrument, proposed action, decision timestamp, strategy version, and evidence bundle hash before any agent runs.

#### Scenario: Strategy produces a reviewable candidate
- **WHEN** a prediction strategy produces a BTC 15-minute candidate that passes the initial deterministic eligibility checks
- **THEN** the coordinator creates one council run linked to that immutable candidate and evidence bundle

#### Scenario: No candidate exists
- **WHEN** a strategy returns hold or no eligible candidate
- **THEN** the coordinator does not ask a council to invent a trade

### Requirement: Hierarchical specialist routing
The coordinator MUST resolve a versioned council profile by domain and specialization key. Prediction and perpetual profiles MUST support asset-specific specialization, and sports profiles MUST support sport, league, and market-class specialization without requiring separate orchestration code.

#### Scenario: Crypto candidate routes by asset
- **WHEN** the coordinator receives an ETH perpetual candidate
- **THEN** it selects the configured `perp/ETH/<strategy-class>` profile or returns hold when no compatible profile exists

#### Scenario: Sports candidate routes by taxonomy
- **WHEN** the coordinator receives an NBA pre-game moneyline candidate
- **THEN** it selects a sports profile compatible with basketball, NBA, and pre-game moneyline

### Requirement: Blind independent first round
The coordinator SHALL run the required first-round roles independently and concurrently subject to configured concurrency limits. A first-round agent MUST NOT receive another first-round agent's verdict, identity, private reasoning, or mutable conversation state.

#### Scenario: Bull and bear reviews run
- **WHEN** a candidate enters first-round review
- **THEN** the bull and bear roles receive independently generated requests over the same evidence-bundle version

### Requirement: Required council roles
Every enabled council profile MUST declare research, bull thesis, bear thesis, skeptic, execution/liquidity, rules/settlement, portfolio risk, and master synthesis roles, and MUST classify each role as critical, advisory, or non-voting.

#### Scenario: Critical role is missing
- **WHEN** a profile omits rules/settlement or another role marked critical by domain policy
- **THEN** profile validation fails before the council can be enabled

### Requirement: Deterministic quorum and veto calculation
The system SHALL calculate quorum, critical-role completion, abstentions, and vetoes with versioned deterministic policy. A master model MUST NOT alter vote weights, clear a veto, or declare quorum.

#### Scenario: Settlement validator blocks
- **WHEN** rules/settlement returns a valid block for ambiguous resolution terms
- **THEN** deterministic council policy produces hold regardless of the other agents' support

#### Scenario: Subjective majority supports a trade
- **WHEN** most directional roles support a candidate but a required role times out
- **THEN** quorum fails and the council result is hold

### Requirement: Bounded reconsideration
The coordinator MAY run at most one critique/revision round for a council run. A revision request MUST contain only validated claims, evidence references, and explicit objections, and MUST NOT introduce uncaptured external facts.

#### Scenario: Resolvable disagreement receives one revision
- **WHEN** bull and bear verdicts conflict on the interpretation of an existing evidence item and policy permits reconsideration
- **THEN** the coordinator runs one revision round and records each revised artifact as a new attempt

#### Scenario: Disagreement remains after revision
- **WHEN** the revision round does not resolve a required objection
- **THEN** the final council outcome is hold and no third round is started

### Requirement: Constrained master synthesis
The master synthesizer SHALL consume only validated council artifacts and deterministic policy results. It MUST return take, hold, or reject with supporting verdict IDs, dissenting verdict IDs, invalidation conditions, and any proposed price or size ceilings, and MUST NOT cite evidence absent from the bundle.

#### Scenario: Master recommends take
- **WHEN** deterministic quorum passes, no veto remains, and the master returns a schema-valid take artifact
- **THEN** the coordinator records a take recommendation and forwards it to final deterministic admission

#### Scenario: Master output is unsupported
- **WHEN** the master cites an unknown evidence or verdict ID
- **THEN** validation fails and the council returns hold after the allowed format-repair policy is exhausted

### Requirement: Deadline and budget failure is fail-closed
Every profile MUST define per-role and total deadlines, token ceilings, cost ceilings, and concurrency limits. Exceeding a required deadline or budget MUST stop further model work and produce hold without suppressing completed audit artifacts.

#### Scenario: Total council budget is exhausted
- **WHEN** completed role calls consume the configured total cost or token budget before quorum
- **THEN** remaining calls are canceled or not started and the council records hold with `budget_exhausted`

## Model Complexity

Master synthesis and difficult research are high-complexity roles; bull, bear, skeptic, execution narrative, and settlement interpretation are medium-to-high; routing and extraction are low-to-medium; quorum and veto calculation are deterministic. Proposal-time OpenAI/Codex Pro starts are GPT-6 Astra, GPT-5.6 Terra, and GPT-5.6 Luna respectively. Anthropic advisory alternatives are Claude Opus 5 or Claude Fable 5.1 for the hardest synthesis, Claude Sonnet 5 for specialists, and Claude Haiku 4.5 for narrow work. No Anthropic subagent is available in this planning session, so implementation MUST validate those assignments through profile-specific evals.
