## ADDED Requirements

### Requirement: Unauthenticated public gateway boundary
The system SHALL implement a public-data client and `PolymarketUSMarketDataAdapter` against documented endpoints at `https://gateway.polymarket.us`. The client SHALL require no Polymarket API key, signing key, wallet, or trading credentials and SHALL expose no authenticated trading or combo API path, including behind a feature flag. Discovery, quote, book, settlement metadata, and history operations SHALL be read-only and capability-declared.

#### Scenario: Default installation has no Polymarket credentials
- **WHEN** the operator runs a public scan with no Polymarket secret configured
- **THEN** the client can retrieve supported public data without authentication or a wallet prompt

#### Scenario: Unsupported authenticated feature is requested
- **WHEN** a caller asks for an order, account balance, or authenticated combo quote
- **THEN** the client reports that the operation is outside its capabilities and makes no authenticated request

### Requirement: Documented endpoint discovery and normalization
The client SHALL maintain a verified endpoint/capability mapping rather than assume a single API version. It SHALL support documented sports, leagues, events, markets, market lookup, BBO, books, and history where available, including `GET /v2/leagues/{slug}/events`. League-event normalization SHALL preserve nested events, markets and sides, `sportradarGameId`, participant IDs, live/closed/ended flags, start time, market type, quote semantics, tradability, minimum quantity, and `feeCoefficient`. Unsupported capabilities and absent leagues SHALL be represented explicitly.

#### Scenario: Nested league event contains an untradable side
- **WHEN** a response includes a market side marked untradable
- **THEN** normalization preserves the side and its status without presenting its indicative price as an executable ask

#### Scenario: Desired league has no supported listing
- **WHEN** discovery finds no eligible listed markets for a configured league
- **THEN** the scan records absent coverage without inventing a market or treating the league allowlist as proof of venue support

### Requirement: Complete bounded pagination
The client SHALL follow each endpoint's documented pagination, deduplicate stable venue identities, and bound page count and elapsed time. Repeated pages, invalid pagination, partial failure, and truncation SHALL be visible in the result and source health. The client MUST NOT silently label an incomplete discovery response as complete.

#### Scenario: API repeats the same page
- **WHEN** pagination returns identities already seen without progress
- **THEN** the client stops within its configured bound and records a structured incomplete-discovery reason

#### Scenario: Later page fails
- **WHEN** an early page succeeds and a subsequent page exhausts retries
- **THEN** retained rows remain auditable and the scan records partial coverage rather than a successful complete universe

### Requirement: Conservative shared rate limiting and resilient transport
The client SHALL use connection pooling, explicit timeouts, bounded concurrency, exponential backoff, bounded retries, and structured errors. Rate-limit defaults SHALL remain below the verified 20 requests/second per-IP public limit documented in the integration report and SHALL be reverified against primary documentation before implementation. Simultaneous scans and retries on the supported single-node deployment SHALL share a rate budget. HTTP 429 SHALL honor applicable server retry guidance; repeated 429, transient 5xx, and timeouts SHALL exhaust bounded retries and degrade source health. Permanent client errors SHALL not be retried indefinitely.

#### Scenario: Concurrent jobs encounter rate limiting
- **WHEN** multiple requests receive HTTP 429
- **THEN** retries respect the shared limiter and retry guidance and terminate after the configured retry or time budget

#### Scenario: Permanent invalid request
- **WHEN** an endpoint returns a nonretryable validation error
- **THEN** the client persists a structured error and does not enter a retry loop

### Requirement: Reference caching and executable freshness
The client SHALL cache reference data using explicit TTLs and distinguish reference-data caching from price freshness. Quotes and books SHALL include source and availability timestamps, be checked for age and future-time inconsistency, and remain subject to scanner freshness and depth requirements. Cached or stale prices MUST NOT become fresh merely because they were read again. Last trade, midpoint, side probability, and complementary bid SHALL not substitute for an undocumented executable ask.

#### Scenario: Cached quote outlives its freshness budget
- **WHEN** a scan retrieves a cached quote older than the configured maximum age
- **THEN** the quote remains marked stale and cannot qualify a candidate even if reference-data cache health is good

#### Scenario: Market response includes a price but no executable ask
- **WHEN** the response exposes only an indicative or last-traded price
- **THEN** the client preserves its price type and the scanner rejects it as an entry-price source

### Requirement: Response validation and audit retention
The client SHALL validate required payload shape, numeric ranges, identities, and timestamps without discarding unknown fields from raw audit material. Every fetch SHALL retain source endpoint, request parameters excluding secrets, response/retrieval status, timestamps, and raw-response reference or hash under applicable retention policy. Invalid payloads SHALL produce traceable errors and MUST NOT silently normalize into qualifying defaults.

#### Scenario: Response changes a required field type
- **WHEN** a quote price arrives in an unsupported shape
- **THEN** the client records the source response and validation error and excludes the malformed quote

### Requirement: Public-data acceptance evidence
Phase 2 acceptance SHALL require recorded or mocked payload tests for normalization, pagination, missing fields, timeout/429/5xx handling, rate bounds, caching, stale detection, fee provenance, and unauthenticated-only request routing. Network integration tests SHALL be separately marked and disabled by default. Documentation verification SHALL record endpoint, fee, rounding, and rate-limit source dates, including the reported 0.0695 default effective 2026-09-17, without treating a planning-time value as permanently current.

#### Scenario: Default test suite runs offline
- **WHEN** normal tests execute without network access or external credentials
- **THEN** public-client tests pass against controlled fixtures and live integration calls are not attempted
