## ADDED Requirements

### Requirement: Registry-driven manual crypto collection
Manual collection SHALL select 15-minute and hourly event series and spot
symbols from the asset registry, not a BTC-only constant. It MUST preserve the
foreground/manual execution policy and per-series resumable behavior. Event
cadence and candle sampling period MUST remain distinct: hourly markets require
fine enough candles for entry simulation and MUST NOT be reduced to one candle
at market close.

#### Scenario: Operator runs a default collection pass
- **WHEN** the operator invokes the historical collector without an explicit asset override
- **THEN** the collector SHALL process every registry asset in at least `observe` mode with a validated event or spot mapping and report per-asset results

### Requirement: Asset- and cadence-aware coverage and qualification evidence
The system SHALL calculate and persist/display per-series coverage windows, gap
counts, quote liveness, spread, depth, open interest, and recent volume needed
by each asset and cadence's configured eligibility policy. A stale or unavailable
value MUST be labeled as such.

#### Scenario: Market has only one quoted side
- **WHEN** a configured asset's market lacks either a usable bid or ask
- **THEN** its market-liveness result SHALL be ineligible and no execution path SHALL treat it as tradeable

### Requirement: Spot-feed support is explicit
The collector SHALL fetch spot history only from a registry-approved feed/symbol
mapping. It MUST not silently substitute BTC or another asset's spot history
when an asset feed is unsupported or fails.

#### Scenario: Altcoin feed is unavailable
- **WHEN** all approved spot feeds for an enabled asset fail or return no valid data
- **THEN** the asset SHALL report `spot_feed_unavailable` and SHALL not become eligible for strategies requiring spot inputs
