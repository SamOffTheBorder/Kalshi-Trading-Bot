## ADDED Requirements

### Requirement: Account and ledger isolation
Portfolio data SHALL be scoped by domain, venue, mode, account and run. Backtest, shadow and paper outcomes SHALL remain distinct. Aggregation SHALL require compatible currency/time/valuation and disjoint capital ledgers with included accounts disclosed.

#### Scenario: Compare duplicate paper capital
- **WHEN** two experimental accounts each use the same simulated starting capital
- **THEN** comparison shows separate results and does not present their sum as one funded portfolio.

### Requirement: Defined accounting and unavailable values
P&L SHALL follow the existing domain ledger convention, identify realized/unrealized/net values, fees and funding without double-counting, valuation basis and age, window and timezone. Unknown values SHALL remain unavailable; partial coverage SHALL be labeled. Returns SHALL require a known denominator; undefined ratios SHALL be identified.

#### Scenario: Missing position mark
- **WHEN** an open position lacks a current valuation
- **THEN** its unrealized P&L and dependent totals are marked incomplete/unavailable with reason rather than zero, while available realized results remain visible.

### Requirement: Position and execution lineage
Positions SHALL show side, quantity, entry, mark, P&L, fees, strategy/run and domain-appropriate settlement/funding/risk fields, with links to recorded orders, fills and originating decisions. Order history SHALL distinguish partial, rejected, canceled and filled states where recorded and identify domains without order lifecycle records.

#### Scenario: Fill without order lifecycle
- **WHEN** a domain provides a fill ledger but no order-state events
- **THEN** the fill remains inspectable with source IDs and the UI states Order lifecycle not recorded without inventing an order timeline.

### Requirement: Visible risk policy and usage
Risk views SHALL show recorded daily loss, drawdown, sizing/exposure limits and usage with units and denominators, admission/reconciliation blockers, and supported concentration/leveraged-risk measures. Limits SHALL remain read-only and server risk policy SHALL remain authoritative.

#### Scenario: Risk block active
- **WHEN** a daily-loss guard blocks new entries
- **THEN** the page displays current usage, policy threshold and block reason in the correct scope and does not offer a display-only override.

### Requirement: Performance journal and export
Performance SHALL show scoped equity/drawdown and supported attribution with sample size, period and metric definitions. Journal notes/tags SHALL attach to stable run/trade IDs. Filtered CSV/session exports SHALL match the selected scope and include units, timezone, source IDs and incomplete-data flags, sanitize formula-like free text and exclude secrets.

#### Scenario: Export scoped review
- **WHEN** the operator exports one paper account and date range containing a journal note beginning with a spreadsheet formula prefix
- **THEN** only matching records are exported with declared units/timezone and the note is escaped as inert text.

## Model complexity

High-complexity cross-capability contract. Follow the model allocation and escalation rules in `../../design.md`: GPT-6 Astra for requirements and control/accounting review; Claude Opus 5 is an advisory user-selected alternative. Bounded presentation work can use the documented lighter allocation only after contracts are fixed. Revisit when data coverage or execution dependencies change.

