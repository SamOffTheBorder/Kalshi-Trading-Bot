# kalshi-market-data

## ADDED Requirements

### Requirement: No unattended background collection
The system SHALL NOT rely on OS-level process supervision, auto-restart, or scheduled/background execution for data collection. All collection (periodic backfill and the short-cadence collector alike) SHALL be operator-initiated and run only while explicitly started, per user decision (2026-09-04): nothing runs when the operator is not actively running it.

#### Scenario: Operator closes the collector
- **WHEN** the operator stops or closes a running collection process
- **THEN** nothing restarts it automatically, and no alarm fires for its absence

### Requirement: Crypto-only collection
Data collection SHALL be limited to crypto series (`KXBTC`, `KXBTCD`, `KXBTC15M`, `KXETH`, `KXETHD`) and perpetual futures. Weather series SHALL NOT be collected going forward; previously archived weather data may remain in storage for reference.

#### Scenario: Weather excluded from new passes
- **WHEN** a collection pass runs
- **THEN** no weather series are fetched

### Requirement: Short-cadence market history via settled candlesticks
The system SHALL collect fifteen-minute-cadence markets (`KXBTC15M`) using the same settled-market candlestick pipeline used for other series, at one-minute period granularity. No dedicated near-real-time collector is required: verified live (2026-09-04), a settled `KXBTC15M` market's full one-minute bid/ask/open-interest/volume history is retrievable via the standard candlestick endpoint, the same as any other settled market, within Kalshi's normal rolling window.

#### Scenario: Fifteen-minute window captured after settlement
- **WHEN** a fifteen-minute market settles and a collection pass runs afterward, before the market rolls off Kalshi's history window
- **THEN** the stored history contains one-minute quote observations from within that window and its final outcome

### Requirement: Perpetual futures history
The system SHALL archive perpetual-futures mark prices, historical funding rates, and realized funding payments.

#### Scenario: Funding history stored
- **WHEN** a funding interval elapses
- **THEN** the funding rate for that interval is retrievable from storage

### Requirement: Market liveness is recorded
Stored market observations SHALL retain the information needed to determine, after the fact, whether a market had a two-sided quote and non-zero open interest at that time.

#### Scenario: Liveness reconstructable
- **WHEN** a historical bar is loaded for backtesting
- **THEN** whether the market was two-sided with non-zero open interest at that timestamp can be determined from stored fields
