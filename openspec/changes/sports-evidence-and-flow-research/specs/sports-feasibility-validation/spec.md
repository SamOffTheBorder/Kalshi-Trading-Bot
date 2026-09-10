## ADDED Requirements

### Requirement: Flow and evidence candidates use the existing feasibility gate
Flow-only, evidence-only, combined, and market-baseline candidates SHALL use
the same chronological holdout, calibration, fee-adjusted fill, executable
size, concentration, and drawdown gates.

#### Scenario: Combined candidate outperforms only before leakage checks
- **WHEN** a candidate's advantage disappears after causal filtering or
  execution costs
- **THEN** the report marks it `park` or `insufficient_data` and never
  authorizes execution

### Requirement: Research comparisons are reproducible
Every feasibility report SHALL include feature versions, evidence-card hashes,
model identity, prompt/output hashes when LLMs were used, and the exact
holdout boundary.

#### Scenario: Operator reruns a frozen report
- **WHEN** the same captured observations and configuration are supplied
- **THEN** the report can reproduce the same candidate inputs and benchmark
  classification without making new web requests
