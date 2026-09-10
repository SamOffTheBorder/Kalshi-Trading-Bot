## ADDED Requirements

### Requirement: Local LLM review is structured and fail-closed
The local Ollama adapter SHALL accept structured market/evidence inputs and
return a schema-validated summary, classification, or veto. Unreachable,
timed-out, or malformed responses SHALL become an unavailable/rejected result.

#### Scenario: Local model is unavailable
- **WHEN** Ollama cannot answer a requested review
- **THEN** the result is persisted as unavailable and no candidate is
  approved by the model

### Requirement: OpenRouter is a slow-path research adapter
The OpenRouter adapter SHALL be opt-in and limited to non-latency-critical
web retrieval, daily/weekly research briefs, and post-mortems. Requests SHALL
retain citations, model identity, prompt/output hashes, and retrieval time.

#### Scenario: Hosted research provider is unavailable
- **WHEN** an OpenRouter request fails
- **THEN** the current strategy and local review remain unaffected and the
  research result is recorded as unavailable

### Requirement: LLMs cannot originate or execute trades
LLM adapters SHALL not select instruments, originate entry signals, size
positions, alter risk limits, or call order-placement APIs.

#### Scenario: Model recommends an unrequested trade
- **WHEN** an LLM output contains a trade idea without a strategy candidate
- **THEN** the output is rejected as advisory text and no order action occurs

### Requirement: Web retrieval is temporally safe
Evidence retrieved for a simulated decision SHALL be filtered by publication
or observed time and SHALL not include documents first available after that
decision.

#### Scenario: Search result is published after the decision
- **WHEN** a retrieved document timestamp exceeds the simulated decision time
- **THEN** it is excluded and the run records a temporal-leakage rejection
