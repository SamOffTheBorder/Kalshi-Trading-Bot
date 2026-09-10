## ADDED Requirements

### Requirement: Constituent-only composition inputs
The system SHALL compose a reconstructed index series only from sources registered with the `constituent` source role and a quote currency matching the target index's quote currency. A source that is not a documented constituent of the target index, or whose quote currency differs, SHALL be refused as a composition input regardless of its coverage depth or its role in other pipelines. The set of constituents that contributed to a composition SHALL be recorded with the output.

#### Scenario: Non-constituent source is offered to the composer
- **WHEN** a composition request includes a Binance `BTCUSDT` partition
- **THEN** the system SHALL refuse the input, citing non-constituent role and quote-currency mismatch, and SHALL NOT emit a partial series that silently excludes it

#### Scenario: Composition succeeds from two constituents
- **WHEN** Kraken and Coinbase USD trade partitions are supplied for the same window
- **THEN** the system SHALL emit a reconstructed series recording both venues as contributors

### Requirement: One-second grid with explicit gaps
The system SHALL emit the reconstructed series on a one-second grid matching the target index's publication cadence. For each second, each contributing constituent SHALL supply its last observed trade price within that second, and the emitted value SHALL be the median across contributing constituents. A constituent with no observation in a second SHALL contribute nothing for that second and SHALL NOT have a prior value carried forward. Every emitted second SHALL record the number of contributing constituents.

#### Scenario: A constituent is silent for a second
- **WHEN** Coinbase has no trade print during a given second but Kraken does
- **THEN** the system SHALL emit that second with a contributor count of 1 and SHALL NOT forward-fill a Coinbase price into it

#### Scenario: No constituent reports during a second
- **WHEN** no contributing constituent has an observation within a second
- **THEN** the system SHALL record a coverage gap for that second and SHALL NOT emit a value

### Requirement: Reconstructed output is never labelled as the index
The system SHALL persist reconstructed values with `provenance = "reconstructed_index"` and a distinct series identity from any captured index feed. Reconstructed values SHALL NOT be written to the captured-index store, SHALL NOT be merged into a captured-index series, and SHALL NOT be returned by an interface whose contract is to supply captured index readings. A consumer requesting captured index data over a window covered only by reconstruction SHALL receive an empty or insufficient-data result rather than reconstructed values.

#### Scenario: Reconstruction covers a window with no capture
- **WHEN** a caller requests captured BRTI readings for a window where only reconstructed data exists
- **THEN** the system SHALL report insufficient captured data and SHALL NOT substitute reconstructed values

#### Scenario: Reconstructed series is persisted
- **WHEN** a composition run completes
- **THEN** every persisted row SHALL carry `reconstructed_index` provenance, its contributing venue set, and its contributor count

### Requirement: Reconstruction error measured at the resolution timescale
The system SHALL measure reconstruction error only over windows where both captured index readings and reconstructed coverage exist. The report SHALL include the mean and maximum absolute level difference, and SHALL additionally include a resolution-agreement metric: the fraction of simulated contracts over the window for which the reconstructed series and the captured index produce the same settlement outcome under the contract's own resolution rule. A report that omits the resolution-agreement metric SHALL NOT be treated as a validation of the reconstruction.

#### Scenario: Overlapping capture and reconstruction exist
- **WHEN** an operator requests a reconstruction-error report for a window with both series present
- **THEN** the system SHALL report level error and resolution agreement computed under the contract's resolution rule, not tick-level correlation alone

#### Scenario: No captured index data overlaps the reconstruction
- **WHEN** an error report is requested for a window with no captured index readings
- **THEN** the system SHALL report the reconstruction as unmeasured and SHALL NOT report an error figure

### Requirement: Unmeasured reconstruction is treated as unvalidated
The system SHALL treat a reconstruction with no resolution-agreement measurement as unvalidated. An unmeasured reconstruction SHALL remain usable for research and strategy rejection, and SHALL be reported as unmeasured wherever its coverage is displayed. Absence of a measurement SHALL NOT be reported, displayed, or recorded as a passing quality result.

#### Scenario: Coverage is displayed before any capture exists
- **WHEN** the dashboard displays reconstructed coverage and no captured index readings exist
- **THEN** the system SHALL label the reconstruction unmeasured rather than showing a passing or empty quality status
