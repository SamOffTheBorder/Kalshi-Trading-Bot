## ADDED Requirements

### Requirement: Constituent source role
The system SHALL support a `constituent` source role identifying a venue documented as an input to a settlement index, distinct from `primary` (a reproducible archive), `secondary` (an independent cross-check), and `manual_comparison`. A constituent mapping SHALL record the index it is a constituent of, and SHALL be registered only for a venue named in that index's published constituent list. The `constituent` role SHALL NOT be inferred from coverage depth, archive quality, or use as a primary source.

#### Scenario: A deep archive that is not an index input is registered
- **WHEN** a Binance USDT-quoted mapping is registered for BTC
- **THEN** the system SHALL retain its existing role and SHALL NOT assign it the `constituent` role

#### Scenario: A constituent venue is registered
- **WHEN** Kraken BTC-USD is registered against the BRTI index
- **THEN** the mapping SHALL record `constituent` role, the target index identity, and USD as its quote currency

### Requirement: Kraken and Coinbase USD acquisition
The system SHALL acquire BTC, ETH, SOL, and XRP USD history from Kraken's published historical downloads and Coinbase's public market-data API. Acquired artifacts SHALL follow the existing immutable raw-artifact rules: content hash, byte size, source, request or archive URL, native instrument, market type, quote currency, retrieval timestamp, and parser version SHALL be recorded before normalization. Where a source publishes a checksum, the system SHALL verify it and SHALL reject a mismatching artifact. Where a source publishes no checksum, the artifact SHALL record its integrity status as unverified rather than as verified.

#### Scenario: A source publishes no checksum
- **WHEN** an artifact is retrieved from a source that publishes no sidecar checksum
- **THEN** the system SHALL store it with an unverified integrity status and SHALL NOT record it as checksum-verified

#### Scenario: Acquisition is repeated for an unchanged artifact
- **WHEN** the same source artifact is retrieved twice with identical content
- **THEN** the import SHALL be idempotent and SHALL NOT create a duplicate provenance version

### Requirement: Reconstructed partitions are distinguishable in the lake
The system SHALL store reconstructed index partitions in the data lake with a provenance distinct from every source-native partition, and SHALL make that distinction available to manifest construction, coverage reporting, and quality evaluation without inspecting partition contents. A reconstructed partition SHALL NOT be presented as an observation of the venue or index it approximates.

#### Scenario: Coverage is reported across mixed partitions
- **WHEN** a coverage report spans both source-native and reconstructed partitions
- **THEN** the report SHALL separate the two rather than presenting a combined coverage figure

## MODIFIED Requirements

### Requirement: Reproducible primary and secondary source roles
The system SHALL use a configured exchange-native archive/API as the primary underlying-history source and SHALL support an independently sourced secondary comparison feed. The initial primary adapter SHALL support checksum-verifiable Binance public spot and USD-M futures artifacts for BTC/ETH/SOL/XRP where available. The initial secondary adapter SHALL support Coinbase public candle data, marking its known incomplete intervals rather than manufacturing candles. The system SHALL additionally support USD-quoted `constituent` sources — initially Kraken and Coinbase — for index reconstruction. The selected source role, venue, native market type, and quote currency SHALL remain visible in all manifests and reports; observations from different sources SHALL NOT be silently merged into one price series, and a composition that intentionally combines constituent sources SHALL be emitted as a distinct reconstructed series rather than as any contributing venue's series.

#### Scenario: Primary archive is valid
- **WHEN** a requested Binance archive is downloaded and its sidecar checksum matches
- **THEN** the system SHALL store it as a verified primary raw artifact eligible for normalization

#### Scenario: Secondary data has a missing interval
- **WHEN** Coinbase returns no candle for a requested bucket
- **THEN** the system SHALL record a coverage gap and SHALL NOT forward-fill the bucket

#### Scenario: Constituent sources are combined
- **WHEN** Kraken and Coinbase USD series are combined for index reconstruction
- **THEN** the output SHALL be a distinct reconstructed series and neither contributing venue's stored series SHALL be modified

### Requirement: Manual TradingView import boundary
The system SHALL allow an operator to import a TradingView-exported CSV as a manually provided comparison artifact only. The import SHALL preserve the supplied file hash, operator-declared symbol, chart interval, export time, and declared source, and SHALL require explicit mapping review before normalization. TradingView artifacts SHALL NOT be the default automated ingestion source, SHALL NOT overwrite exchange-native data, SHALL NOT be admitted as a `constituent` composition input, and SHALL NOT independently satisfy a data-quality or promotion gate.

#### Scenario: Operator imports a TradingView CSV
- **WHEN** an operator supplies a CSV together with its symbol and interval mapping
- **THEN** the system SHALL store it as `manual_comparison` provenance and report any alignment difference from the primary source

#### Scenario: Training is requested with only manual comparison data
- **WHEN** a candidate manifest contains no verified primary source artifact
- **THEN** the system SHALL classify the result as diagnostic-only and block promotion

#### Scenario: A TradingView artifact is offered for reconstruction
- **WHEN** a composition request includes a `manual_comparison` artifact
- **THEN** the system SHALL refuse it as a composition input
