## ADDED Requirements

### Requirement: Asset and portfolio budget-aware fixed-risk sizing
Fixed-risk sizing SHALL calculate a candidate size from the shared account
equity and the executable stop distance defined by `causal-strategy-validation`
(the actual side-specific executable stop price and both-leg costs, not a
global win-rate threshold), then clamp it to the current per-asset,
correlation-group, portfolio, and exchange constraints before any order is
created. Kelly sizing SHALL NOT be used.

#### Scenario: Candidate exceeds remaining ETH budget
- **WHEN** fixed-R sizing produces an ETH candidate larger than ETH's remaining asset budget
- **THEN** the system SHALL reduce the quantity to a valid exchange increment or reject the entry if no positive valid quantity remains

### Requirement: Unaffordable minimum contracts fail closed
The sizing path SHALL reject a candidate when the permitted risk budget cannot
support the asset's validated minimum event or perpetual contract size. It MUST
not round the position upward beyond a configured limit.

#### Scenario: Altcoin perpetual minimum is too large
- **WHEN** an altcoin perp's minimum order size exceeds the remaining portfolio risk budget
- **THEN** no order SHALL be placed and the decision SHALL record `minimum_size_exceeds_risk_budget`

