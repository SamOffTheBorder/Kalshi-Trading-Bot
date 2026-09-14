# Perp discovery pass

## ADDED Requirements

### Requirement: An operator-facing script runs perp discovery

The system SHALL provide a script that calls `PerpDiscovery.refresh` for
every registry asset with a configured `perp`, persisting a `DiscoveryResult`
row with `instrument="perp"` per asset, mirroring
`scripts/discover_crypto_series.py`'s existing event-side pattern.

#### Scenario: Discovery persists a result per configured perp asset
- **WHEN** the perp discovery script runs against the default registry
- **THEN** a `DiscoveryResult` row with `instrument="perp"` exists for each
  asset with a configured `perp`

#### Scenario: An eligible fresh snapshot clears the discovery gate
- **WHEN** `evaluate_perp_admission` is evaluated for an asset with a fresh,
  eligible perp `DiscoveryResult`
- **THEN** it does not refuse with `no_discovery_snapshot`
- **AND** any remaining refusal reason (e.g. stale marks) is reported
  distinctly from the discovery gate
