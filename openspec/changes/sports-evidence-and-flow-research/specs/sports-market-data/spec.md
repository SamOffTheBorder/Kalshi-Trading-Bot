## ADDED Requirements

### Requirement: Flow and evidence inputs remain joinable to capture sessions
Derived flow features and external evidence identifiers SHALL join to the
captured market ticker, rule-provenance version, capture session, and causal
availability timestamp used by validation.

#### Scenario: Validation loads a combined candidate
- **WHEN** a run loads flow and evidence inputs for a market
- **THEN** it can identify the exact market terms, source versions, and
  observations available at the decision time
