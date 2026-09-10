## ADDED Requirements

### Requirement: Sports market data is captured causally in foreground sessions
The system SHALL collect sports market candles, available order-book snapshots,
and available public trades only during an operator-initiated foreground
session. Every stored observation SHALL include observed time when the source
provides it, local availability time, capture-session ID, source endpoint, and
provenance.

#### Scenario: Operator stops a capture session
- **WHEN** the operator closes or interrupts a sports capture session
- **THEN** collection stops and nothing schedules, restarts, or backfills an
  unavailable live observation automatically

#### Scenario: Causal timestamp is retained
- **WHEN** an order-book or public-trade response supplies an exchange event
  time
- **THEN** the stored record preserves that event time separately from local
  receipt time

### Requirement: Data gaps are visible rather than fabricated
The system SHALL record or report missing observation intervals and SHALL NOT
interpolate order-book, trade, score, lineup, or external-reference values for
the purpose of backtesting.

#### Scenario: Capture session has a gap
- **WHEN** consecutive observations exceed the configured capture interval by
  the configured gap threshold
- **THEN** the gap is reported and no synthetic observations are inserted

### Requirement: Market-specific terms accompany captured data
Captured sports market data SHALL be joinable to the discovered contract's
rule provenance, settlement source, outcome shape, and fee metadata.

#### Scenario: Validation loads a captured market
- **WHEN** a sports validation run loads observations for a market
- **THEN** it can retrieve the exact rule and fee metadata associated with the
  captured market identity

### Requirement: External sports feeds are opt-in and attributable
An external odds, lineup, injury, or live-play feed SHALL NOT be used unless a
configured adapter records its provider identity, endpoint, observed time,
availability time, and provenance with each imported observation.

#### Scenario: Unconfigured external feed
- **WHEN** a sports validation run is started without a configured external
  feed adapter
- **THEN** it runs only on the supported Kalshi-derived inputs and does not
  fabricate external features
