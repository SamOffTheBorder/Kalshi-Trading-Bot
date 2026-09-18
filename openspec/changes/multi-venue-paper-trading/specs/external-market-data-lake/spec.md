## ADDED Requirements

### Requirement: Active crypto universe and source configuration
The system SHALL ship BTC, ETH, SOL, and XRP as the only active crypto assets for external-data import, strategy research, dashboard filtering, and paper-run admission. Each configured source/instrument mapping SHALL identify asset, venue, market type, native symbol, quote currency, expected cadence support, source role, and enabled state. Any unconfigured asset or a symbol returned by discovery that is not in the active universe SHALL be retained only as an explicitly non-active observation and SHALL NOT be admitted to a training, backtest, shadow, or paper run.

#### Scenario: Default source request has the intended universe
- **WHEN** an operator runs external data discovery without an asset override
- **THEN** the system SHALL request or display only BTC, ETH, SOL, and XRP mappings

#### Scenario: Unconfigured discovery result is returned
- **WHEN** a data provider lists a valid crypto market for DOGE
- **THEN** the system SHALL record it as unconfigured/non-active and SHALL NOT create a paper-eligible instrument

### Requirement: Reproducible primary and secondary source roles
The system SHALL use a configured exchange-native archive/API as the primary underlying-history source and SHALL support an independently sourced secondary comparison feed. The initial primary adapter SHALL support checksum-verifiable Binance public spot and USD-M futures artifacts for BTC/ETH/SOL/XRP where available. The initial secondary adapter SHALL support Coinbase public candle data, marking its known incomplete intervals rather than manufacturing candles. The selected source role, venue, native market type, and quote currency SHALL remain visible in all manifests and reports; observations from different sources SHALL NOT be silently merged into one price series.

#### Scenario: Primary archive is valid
- **WHEN** a requested Binance archive is downloaded and its sidecar checksum matches
- **THEN** the system SHALL store it as a verified primary raw artifact eligible for normalization

#### Scenario: Secondary data has a missing interval
- **WHEN** Coinbase returns no candle for a requested bucket
- **THEN** the system SHALL record a coverage gap and SHALL NOT forward-fill the bucket

### Requirement: Immutable raw artifacts and provenance
The system SHALL persist an immutable raw-artifact record before derived observations are used in a reproducible run. The record SHALL include content hash, byte size, source, request/archive URL, native instrument, market type, quote currency, retrieval timestamp, provider timestamp/version when available, checksum status, parser version, and storage location. Reimporting identical content for the same source/version SHALL be idempotent; a revised provider artifact SHALL create a distinct version rather than overwrite the first artifact.

#### Scenario: Artifact checksum fails
- **WHEN** a downloaded archive checksum does not match the published checksum
- **THEN** the system SHALL mark the artifact rejected, emit an integrity failure, and SHALL NOT normalize or train from it

#### Scenario: Provider revises an archive
- **WHEN** an artifact at a previously imported URL has different content
- **THEN** the system SHALL retain the prior artifact and create a new provenance version for the new content

### Requirement: Causal normalization and quality reporting
The system SHALL normalize supported OHLCV bars, aggregate trades, funding observations, and captured book snapshots without losing source semantics. Every record SHALL include UTC `observed_at`, `available_at`, `retrieved_at`, source identity, native instrument, market type, quote currency, parser/normalization version, and quality status. A bar SHALL not be available to a decision before its close and availability timestamps; a record with unknown availability SHALL be conservative and unavailable until retrieval. The importer SHALL reject malformed timestamps, mixed time units, non-monotonic sequence/trade IDs, invalid prices/sizes, and duplicate idempotency keys, and SHALL produce coverage, gap, rejection, and source-lag reports.

#### Scenario: Incomplete current bar is encountered
- **WHEN** a 15-minute bar has not yet reached its close timestamp at a decision time
- **THEN** the feature builder SHALL exclude that bar from the decision inputs

#### Scenario: Millisecond and microsecond timestamps are mixed
- **WHEN** an artifact contains timestamps inconsistent with its declared unit
- **THEN** normalization SHALL reject the affected artifact/version and report the timestamp-unit fault

### Requirement: Dataset manifests and reproducible access
The system SHALL create an immutable dataset manifest before training, backtesting, or paper-admission validation. A manifest SHALL enumerate raw artifact hashes, normalized partitions/row ranges, source/instrument mappings, coverage and gap summary, time window, filter rules, parser and feature versions, code revision, and configuration hash. A run SHALL load exactly the data declared in its manifest and SHALL fail closed if an artifact is unavailable, rejected, or altered. The system SHALL retain manifests and reports even when later source data changes.

#### Scenario: Backtest starts from a frozen manifest
- **WHEN** an operator starts a validation run with a manifest ID
- **THEN** the reported data fingerprint SHALL match the manifest and no later artifact SHALL enter the run

#### Scenario: Required manifest partition is missing
- **WHEN** a required raw/normalized partition cannot be read
- **THEN** the run SHALL terminate as insufficient data instead of silently using a newer or alternate partition

### Requirement: Manual TradingView import boundary
The system SHALL allow an operator to import a TradingView-exported CSV as a manually provided comparison artifact only. The import SHALL preserve the supplied file hash, operator-declared symbol, chart interval, export time, and declared source, and SHALL require explicit mapping review before normalization. TradingView artifacts SHALL NOT be the default automated ingestion source, SHALL NOT overwrite exchange-native data, and SHALL NOT independently satisfy a data-quality or promotion gate.

#### Scenario: Operator imports a TradingView CSV
- **WHEN** an operator supplies a CSV together with its symbol and interval mapping
- **THEN** the system SHALL store it as `manual_comparison` provenance and report any alignment difference from the primary source

#### Scenario: Training is requested with only manual comparison data
- **WHEN** a candidate manifest contains no verified primary source artifact
- **THEN** the system SHALL classify the result as diagnostic-only and block promotion
