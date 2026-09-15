## ADDED Requirements

### Requirement: Search and saved market views
Markets SHALL support text search, domain/venue, lifecycle, asset/category, closing-window, freshness and admission filters; supported liquidity/edge filters; whitelisted sort, pagination, result count, reset and durable watchlists. Unsupported fields SHALL be identified instead of fabricated.

#### Scenario: Missing edge values
- **WHEN** markets with known and unknown edge are sorted by fee-adjusted edge
- **THEN** known values retain defined numeric order and unknown values are labeled unavailable rather than interpreted as zero or actionable.

### Requirement: Instrument-specific quote semantics
Market rows and details SHALL identify instrument/event, venue, domain, quote units, source and age. Prediction quotes SHALL identify YES/NO and cents per contract; perpetual quotes SHALL identify quoted currency. Derived values SHALL be labeled and unavailable depth/volume SHALL remain unavailable.

#### Scenario: Top of book only
- **WHEN** a contract has persisted top-of-book prices but no depth history
- **THEN** the UI shows those quotes with units/source age and displays Depth unavailable without constructing a depth ladder.

### Requirement: Contract detail and settlement context
Instrument detail SHALL expose recorded lifecycle, close time, separately labeled settlement time, rules/source/version when available, related positions and decisions, and price history with units and visible data gaps. Missing rules SHALL be explicitly identified.

#### Scenario: Market closed but unsettled
- **WHEN** a market closes before its settlement is recorded
- **THEN** the detail marks it closed and awaiting settlement without treating closure as a resolved outcome.

### Requirement: Explainable assessments
Assessment detail SHALL show available fair value/probability, executable price basis, fees, slippage assumption, net edge with units, sizing constraints, decision time, freshness and HOLD/admission reasons, linked to evidence. Confidence SHALL NOT be relabeled as win probability without the source definition. Planning views SHALL NOT submit orders.

#### Scenario: Blocked signal drilldown
- **WHEN** the operator opens a positive-edge signal blocked by stale input
- **THEN** the detail shows the observed edge, stale-input reason and source timestamp, and offers evidence inspection without an enabled order-submission action.

## Model complexity

High-complexity cross-capability contract. Follow the model allocation and escalation rules in `../../design.md`: GPT-6 Astra for requirements and control/accounting review; Claude Opus 5 is an advisory user-selected alternative. Bounded presentation work can use the documented lighter allocation only after contracts are fixed. Revisit when data coverage or execution dependencies change.

