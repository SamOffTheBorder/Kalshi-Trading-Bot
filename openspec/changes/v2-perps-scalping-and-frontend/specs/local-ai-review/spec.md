# local-ai-review

## ADDED Requirements

### Requirement: AI vetoes, never originates trades
The AI layer SHALL only approve or reject decisions produced by a strategy. It SHALL NOT generate entry signals, choose instruments, or size positions.

#### Scenario: No trade without a strategy signal
- **WHEN** the AI layer runs with no strategy decision pending
- **THEN** no order is created under any circumstance

### Requirement: Pre-trade review is local and fail-closed
The per-trade review SHALL run against a locally hosted model. If the model is unreachable, times out, or returns output that does not parse into the expected verdict schema, the decision SHALL become HOLD.

#### Scenario: Ollama unreachable
- **WHEN** the local model endpoint is down and a trade is pending review
- **THEN** the trade is not placed and the reason is recorded

#### Scenario: Malformed model output
- **WHEN** the model returns text that does not parse as the verdict schema
- **THEN** the trade is not placed

### Requirement: Latency budget for the fast path
The per-trade review SHALL complete within a configured timeout appropriate to the trading cadence, and exceeding it SHALL be treated as a failure per the fail-closed rule.

#### Scenario: Review exceeds timeout
- **WHEN** the local model has not responded within the configured timeout
- **THEN** the request is abandoned and the decision becomes HOLD

### Requirement: External LLM calls are off the trade path
Calls to hosted external models SHALL be limited to non-latency-critical work — news retrieval, periodic strategy review, and post-mortems — and SHALL NOT block order placement.

#### Scenario: External provider outage does not stop trading
- **WHEN** the external provider is unavailable
- **THEN** trading continues using local review only

### Requirement: AI verdicts are persisted and auditable
Every AI verdict SHALL be stored alongside the decision it reviewed, including model identity and the parsed verdict, so its predictive value can be measured against realized outcomes.

#### Scenario: Verdict retrievable with outcome
- **WHEN** a reviewed trade has settled
- **THEN** the stored verdict and the realized outcome can be joined for evaluation
