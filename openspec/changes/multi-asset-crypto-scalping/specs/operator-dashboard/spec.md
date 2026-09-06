## ADDED Requirements

### Requirement: Asset- and cadence-aware operational status
The dashboard SHALL show every registered asset's lifecycle mode for each
15-minute and hourly event instrument, event/perp discovery status, instrument
compatibility, data coverage, liveness/eligibility state, and most recent
failure reason. It SHALL replace BTC-specific coverage labels with generic
crypto-asset/cadence views.

#### Scenario: Market discovery is stale
- **WHEN** an asset's latest discovery/eligibility snapshot is older than its configured freshness window
- **THEN** the dashboard SHALL display it as stale or unavailable and SHALL not show it as execution-eligible

### Requirement: Portfolio-risk visibility
The dashboard SHALL display aggregate crypto exposure and each asset's
per-asset and correlation-group usage, including the reason a pending decision
was blocked or reduced.

#### Scenario: Shared group cap blocks SOL
- **WHEN** a SOL entry is rejected because the major-crypto group is fully allocated
- **THEN** the dashboard SHALL show the group usage and `correlation_group_cap` for that decision

### Requirement: Honest mode display
The dashboard SHALL visibly distinguish observe, backtest, paper, and live
assets and SHALL not render an observation-only asset as tradable. Promotion
evidence panels SHALL follow `causal-strategy-validation`: legacy v2 backtest
metrics SHALL be labeled diagnostic-only and SHALL NOT be shown as satisfying
an asset's paper or live gate.

#### Scenario: ZEC is observation-only
- **WHEN** ZEC is configured in `observe` mode
- **THEN** the dashboard SHALL show its collected data and eligibility diagnostics but SHALL not present an arm/trade control for ZEC

#### Scenario: Legacy metric shown for a candidate asset
- **WHEN** an asset's only positive result comes from a pre-rebuild v2 backtest run
- **THEN** the dashboard SHALL mark it diagnostic-only and SHALL show the asset's gate as not cleared
