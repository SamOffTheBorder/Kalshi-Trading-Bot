## ADDED Requirements

### Requirement: Canonical venue and instrument identity
The system SHALL represent research venues, events, instruments, contract sides, quotes, books, resolution rules, fee schedules, and scan candidates through venue-neutral contracts inside `kalshi_bot`. Canonical IDs SHALL be distinct from venue external IDs, and external IDs SHALL be namespaced by venue. Records SHALL preserve sport, league, category, event and market relationship, participant/side mapping, start and close times, status, resolution source and full rules, and raw payload provenance. A Polymarket identifier MUST NOT be stored as a Kalshi `market_ticker`.

#### Scenario: Identical external identifiers on different venues
- **WHEN** Kalshi and Polymarket US return the same external identifier string
- **THEN** the canonical records remain distinct and each retains its venue and original external identifier

#### Scenario: Source metadata is incomplete
- **WHEN** an adapter receives a market without sufficient side or settlement metadata
- **THEN** the record retains the raw source and missing-field status and cannot qualify for automated ranking

### Requirement: Explicit financial units and causal provenance
The system SHALL represent canonical prices and monetary amounts with decimal precision and explicit units, preserve venue-native tick size and quantity increments, and distinguish price, probability, contract count, stake, fee, and depth. Quote and book records SHALL retain source time, observation/retrieval time, availability time, source identity, and immutable raw-payload reference or hash. Normalization MUST NOT silently round a venue-native value into Kalshi cents or treat retrieval time as source time.

#### Scenario: Venue price precision exceeds whole cents
- **WHEN** a valid source quote contains precision beyond one cent
- **THEN** normalization preserves that precision and its units without passing through an integer-cent execution field

#### Scenario: Replay predates availability
- **WHEN** a quote has a source timestamp before a replay cutoff but became available afterward
- **THEN** it is excluded from that replay's eligible inputs

### Requirement: Read-only market-data adapter contract
The system SHALL expose a separate `MarketDataAdapter` protocol for `list_sports`, `list_leagues`, `list_events`, `list_markets`, `get_market`, `get_bbo`, `get_order_book`, `get_price_history`, and supported quote streaming. Adapters SHALL declare capabilities and report unsupported operations explicitly. API-specific payload parsing SHALL remain inside adapters. The research contract MUST NOT expose orders, balances requiring authentication, wallet connections, or execution through `BrokerAdapter`.

#### Scenario: Unsupported quote stream
- **WHEN** a caller requests streaming from an adapter that only supports polling
- **THEN** the adapter reports the unsupported capability and the caller uses a documented polling path without claiming a working stream

#### Scenario: Scanner consumes a canonical market
- **WHEN** the scanner evaluates an adapter result
- **THEN** it uses canonical fields without parsing an API-specific raw payload or invoking a broker

### Requirement: Kalshi compatibility is preserved
The system SHALL provide `KalshiMarketDataAdapter` as a compatibility wrapper over existing public-data behavior. Existing Kalshi identifiers, fee semantics, stored rows, strategies, global bankroll settings, execution interfaces, package imports, and command behavior SHALL remain valid. This change MUST NOT rename `kalshi_bot`, reinterpret historical rows, or generalize execution ledgers to implement the read-only scanner.

#### Scenario: Existing Kalshi regression suite runs
- **WHEN** venue-neutral contracts and the Kalshi wrapper are introduced
- **THEN** every previously passing Kalshi test continues to pass and existing consumers receive equivalent values and identifiers

#### Scenario: Historical Kalshi row is loaded after migration
- **WHEN** a legacy row with `market_ticker` is read
- **THEN** its original Kalshi meaning is preserved and no Polymarket identity is inferred

### Requirement: Venue-specific fee schedules
The system SHALL use a shared fee interface with independent Kalshi and Polymarket implementations. Each fee result SHALL retain venue, formula version, coefficient, effective date, source, rounding mode, assumed quantity, price, and aggregation scope. Polymarket fee calculation SHALL use documented decimal arithmetic for `coefficient * contracts * price * (1 - price)` and documented half-even cent rounding, including cumulative taker-fill adjustments where relevant to an estimate. A valid applicable per-market coefficient SHALL take precedence over the effective documented default. Missing, invalid, conflicting, or temporally inapplicable fee semantics SHALL block ranking until resolved.

#### Scenario: Per-market coefficient overrides the default
- **WHEN** a valid market coefficient differs from the verified effective default
- **THEN** the estimate uses the market coefficient and records both its source and the selected schedule

#### Scenario: Half-cent fee boundary and cumulative fills
- **WHEN** known-answer fixtures exercise exact half-cent values and multiple fills for one estimated order
- **THEN** Polymarket results follow the documented half-even and cumulative adjustment rules while Kalshi results retain existing ceiling semantics

#### Scenario: Historical replay spans a schedule change
- **WHEN** a scan is replayed from a date preceding a fee change
- **THEN** it uses the frozen schedule applicable to that scan rather than the current default

### Requirement: Scope and architecture acceptance gate
Phase 1 acceptance SHALL require adapter contract tests, identity and unit round trips, independent fee fixtures, and the existing Kalshi regression suite. Architecture and acceptance review SHALL follow the proposal's high-complexity allocation: GPT-6 Astra, with Claude Opus 5 as an availability-verified advisory alternative; bounded implementation SHALL follow GPT-5.6 Sol/Terra or advisory Claude Sonnet 5, with GPT-5.6 Luna limited to mechanical work under fixed contracts. Identity, financial-unit, fee, migration, security, cross-change uncertainty, or two failed attempts SHALL trigger architecture-class review rather than relaxed requirements.

#### Scenario: Financial semantics remain uncertain
- **WHEN** an implementation cannot demonstrate a documented fee or identity interpretation
- **THEN** phase acceptance remains blocked and the unresolved decision and escalation are recorded in the change checkpoint
