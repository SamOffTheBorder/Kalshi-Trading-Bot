# kalshi-market-data

## ADDED Requirements

### Requirement: Public market data requires no credentials
The system SHALL fetch Kalshi public market data (markets, events, series, historical candlesticks) without any configured credentials. Backtesting MUST be fully functional on a machine with an empty `.env`.

#### Scenario: Candlestick fetch with no credentials
- **WHEN** `scripts/fetch_historical.py` runs on a machine with no Kalshi credentials configured
- **THEN** historical candlesticks for the requested series are fetched and stored without error

### Requirement: Historical candlesticks are stored in the schema of record
The system SHALL persist fetched candlesticks (1min, 60min, or 1440min periods) to the SQLAlchemy schema with market ticker, period, open/high/low/close prices, volume, and timestamp, deduplicating on re-fetch.

#### Scenario: Idempotent re-fetch
- **WHEN** the same series and date range is fetched twice
- **THEN** the second fetch stores no duplicate rows and the candle count is unchanged

### Requirement: Rate limits are respected client-side
The Kalshi client SHALL enforce a client-side rate limit at or below the Basic tier (20 reads/sec) with exponential backoff on HTTP 429 and 5xx responses, and MUST NOT retry on 401/403.

#### Scenario: Backoff on rate limiting
- **WHEN** the API returns HTTP 429
- **THEN** the client retries with exponential backoff up to a bounded attempt count

#### Scenario: Auth errors fail fast
- **WHEN** the API returns HTTP 401
- **THEN** the client raises immediately without retrying

### Requirement: Data availability is verifiable per series
The system SHALL provide a way to report, per series ticker, the earliest and latest stored candle and any gaps larger than the candle period, so out-of-sample split viability can be assessed before a backtest run.

#### Scenario: Coverage report
- **WHEN** the coverage report is requested for a stored series
- **THEN** it returns first timestamp, last timestamp, total candles, and detected gaps
