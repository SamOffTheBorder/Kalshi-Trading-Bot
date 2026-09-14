# Perpetual paper execution

## ADDED Requirements

### Requirement: Perp domain is runnable

The paper runner SHALL support `--domain perp`, assembling the existing perp
paper primitives into a run loop with the same preflight, admission, audit,
and reconciliation contract the prediction domain uses.

A perp run SHALL NOT construct an execution client and SHALL NOT call any
order endpoint. Only the simulated perp surface is ever invoked.

#### Scenario: A perp run completes its lifecycle
- **WHEN** a perp paper run is started for an admitted asset
- **THEN** preflight, evaluation, and reconciliation all execute
- **AND** every fill is recorded as a `PerpPaperEvent` against the run

#### Scenario: A perp run never touches an order endpoint
- **WHEN** a perp paper run evaluates and fills
- **THEN** no authenticated order request is issued

### Requirement: Perp admission gates fills

A perp asset SHALL be admitted for fills only when `evaluate_perp_admission`
returns a verdict permitting them. An asset failing admission SHALL remain
admitted for decision recording, with the refusal reason recorded.

#### Scenario: Insufficient mark coverage refuses fills
- **GIVEN** an asset whose mark coverage fails the admission check
- **WHEN** the run evaluates that asset
- **THEN** decisions are recorded and no fill is created
- **AND** the admission reason is persisted on the audit event

### Requirement: Every perp position carries a validated bracket

A perp position SHALL NOT be opened without a stop-loss and take-profit that
`validate_bracket` accepts for its side. A bracket breach SHALL close the
position and record the triggering side.

#### Scenario: A long position is stopped out
- **GIVEN** an open long perp position with a validated bracket
- **WHEN** the mark price falls to or below the stop loss
- **THEN** the position is closed with reason `stop_loss`

#### Scenario: An invalid bracket is refused before entry
- **WHEN** an entry is attempted with a stop above entry on a long
- **THEN** the entry is refused with `long_bracket_order`
- **AND** no position row is created

### Requirement: Funding is applied and attributed

Realized funding SHALL be applied to open positions and recorded as a
distinct event type, kept separate from price-driven PnL so that a
funding-carry result can be read as funding collected net of costs rather
than as a directional outcome.

#### Scenario: Funding accrues separately from price PnL
- **GIVEN** an open perp position across a funding settlement
- **WHEN** funding is applied
- **THEN** `funding_pnl_usd` reflects it
- **AND** `realized_pnl_usd` is unchanged by the funding event alone

### Requirement: Two-leg carry decisions without widening Decision

The perp adapter SHALL support a two-leg decision path, because a
funding-carry evaluation spans a perp leg and an event-contract hedge leg.
The single-instrument `Decision` type SHALL NOT be widened to carry a second
leg.

A carry position SHALL record both legs' costs, so its result is measured as
net carry after both legs' fees rather than as a win rate.

#### Scenario: A carry decision records both legs
- **WHEN** a funding-carry entry is taken
- **THEN** the perp leg and hedge leg are both recorded against the run
- **AND** the expected net carry after both legs' fees is persisted

#### Scenario: Carry is refused when net of fees it does not beat cash
- **GIVEN** a funding rate too small to cover both legs' transaction costs
- **WHEN** the carry decision is evaluated
- **THEN** no position is opened and the refusal reason is recorded
