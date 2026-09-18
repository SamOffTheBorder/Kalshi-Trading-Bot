## ADDED Requirements

### Requirement: Deterministic pre-screen before agent spending
The coordinator SHALL run existing lifecycle, provenance, data-quality, freshness, market-state, and paper-safety checks before invoking agents. A hard failure MUST end the candidate as hold or reject with no model calls.

#### Scenario: Candidate data is stale
- **WHEN** domain freshness policy fails at council pre-screen
- **THEN** the system records the deterministic refusal and incurs no council model cost

### Requirement: Final recheck after council latency
Immediately before a council recommendation can influence a paper decision, the system MUST re-run time-sensitive market, freshness, emergency-halt, bankroll, portfolio-risk, and domain-admission checks using current state.

#### Scenario: Quote expires during review
- **WHEN** the reviewed quote is no longer fresh after council completion
- **THEN** final admission records hold and no simulated fill occurs despite a take recommendation

### Requirement: Deterministic gates have final veto authority
No agent, model majority, master artifact, operator council override, or A2A response SHALL bypass or weaken a deterministic data-integrity, settlement, execution, lifecycle, leverage, liquidity, bankroll, concentration, drawdown, emergency, or paper-safety refusal.

#### Scenario: Council unanimously supports but risk refuses
- **WHEN** every council role supports a candidate and portfolio concentration exceeds policy
- **THEN** the final decision is refused with the risk-policy reason

### Requirement: Council cannot promote lifecycle
Council results MUST NOT change a profile, asset, strategy, or domain lifecycle state. Promotion from fixture to replay, shadow, or a paper influence mode SHALL require an explicit operator action and a frozen passing evaluation report.

#### Scenario: Strong shadow performance is observed
- **WHEN** a council accumulates apparently profitable shadow decisions
- **THEN** the system remains in shadow until the operator supplies the required frozen promotion evidence

### Requirement: Paper influence is monotonic in the advisory stage
In `paper_advisory`, the council MAY convert an otherwise eligible candidate to hold or tighten maximum price or size, but MUST NOT create a direction, increase size, loosen price, or revive a candidate that the base strategy or deterministic admission rejected.

#### Scenario: Base strategy holds
- **WHEN** the base strategy produces hold and the council would prefer a trade
- **THEN** no paper order is created

#### Scenario: Council lowers size
- **WHEN** the base strategy and all deterministic gates allow a candidate and the council returns a smaller valid size ceiling
- **THEN** final sizing uses no more than the smaller ceiling

### Requirement: Paper-only execution boundary
This change SHALL expose no live council mode and SHALL construct agent and council components without live-order clients. A council recommendation MAY influence only shadow or simulated paper behavior after profile promotion.

#### Scenario: Live mode is requested
- **WHEN** an operator attempts to configure council influence for live execution
- **THEN** configuration validation refuses startup

### Requirement: Admission lineage is auditable
The system MUST persist the initial pre-screen, council recommendation, final recheck, risk decision, adapter decision, and simulated fill or refusal as linked append-only records with policy and evidence versions.

#### Scenario: Take recommendation is refused later
- **WHEN** the council recommends take but final admission refuses the candidate
- **THEN** the dashboard and audit query show both outcomes and the exact deterministic refusal reason

## Model Complexity

All authoritative admission, lifecycle, freshness, settlement identity, sizing, leverage, bankroll, concentration, drawdown, emergency, and paper-safety decisions are deterministic Python policy and MUST NOT be delegated to a model. GPT-6 Astra, GPT-5.6 Terra/Luna, Claude Fable 5.1, Claude Opus 5, Claude Sonnet 5, and Claude Haiku 4.5 may explain or critique inputs according to council roles, but none receives veto-override authority. Anthropic assignments are advisory because this session has no Anthropic subagent.
