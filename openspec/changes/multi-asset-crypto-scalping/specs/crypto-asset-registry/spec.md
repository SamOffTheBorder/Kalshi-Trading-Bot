## ADDED Requirements

### Requirement: Canonical crypto asset registry
The system SHALL define one typed registry entry per supported crypto asset. An
entry MUST contain a stable asset ID, display label, lifecycle mode per
instrument/cadence, supported spot-feed mapping, prediction-series mappings for
15-minute and hourly markets when listed, the expected contract shape for each
mapping, and optional perpetual lookup/reference-index metadata. BTC, ETH, SOL,
XRP, DOGE, BNB, HYPE, NEAR, ZEC, and LINK MUST be representable without
code-path-specific ticker constants.

#### Scenario: Unknown asset is rejected
- **WHEN** configuration names an asset or instrument mapping not present in the registry
- **THEN** startup or explicit validation SHALL reject that mapping with an actionable error and SHALL not enable an execution path

### Requirement: Explicit lifecycle authorization
The registry SHALL support `observe`, `backtest`, `paper`, and `live` modes per
asset/instrument/cadence. Collection and display MUST require at least
`observe`; each higher-risk action MUST require its corresponding mode and the
existing global trading controls.

#### Scenario: Observed asset emits a signal
- **WHEN** an asset in `observe` mode has a discoverable, quoted prediction market
- **THEN** the system MAY collect and report it but SHALL reject backtest and order admission for that asset

#### Scenario: Asset is demoted
- **WHEN** an operator changes an asset from `paper` or `live` to a lower mode
- **THEN** new entries SHALL stop immediately while existing positions remain subject to their established exit protections

### Requirement: Discovery validates configured instruments and cadences
The system SHALL explicitly refresh and persist a discovery result for each
configured 15-minute or hourly event series and optional perp. It MUST validate
the declared cadence and contract shape, disable only the affected
instrument/cadence on a missing, malformed, stale, or incompatible discovery
result, and expose the reason.

#### Scenario: Event series is removed or renamed by the venue
- **WHEN** a configured event series cannot be fetched from Kalshi during validation
- **THEN** the asset's event instrument SHALL be ineligible and the system SHALL not substitute a guessed ticker
