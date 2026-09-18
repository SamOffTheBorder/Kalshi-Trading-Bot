## Why

The current v2 implementation hard-codes BTC as the only actively collected,
backtested, and displayed crypto asset, even though Kalshi currently lists
15-minute and hourly prediction markets for ETH, SOL, XRP, DOGE, BNB, HYPE,
NEAR, and ZEC and perpetuals for a partially overlapping set. Adding assets expands
the sample size and the number of independent scalp opportunities, but blindly
enabling every market would multiply correlated risk and recreate the
phantom-liquidity failure that v2 was designed to prevent.

This change introduces a single, explicit asset registry and a staged,
liquidity-gated rollout so ETH can be the first additional tradable asset while
the other supported assets accumulate comparable data and earn their own
promotion to paper and live trading.

## What Changes

- Add an operator-configured crypto asset registry that maps an asset and market
  cadence (15-minute or hourly) to its prediction-market series and contract
  shape, spot-feed symbol, and (only when available)
  perpetual market identity and reference index. Validate all mappings rather
  than scattering BTC/ETH ticker constants through the codebase.
- Add discovery and eligibility checks for Kalshi crypto markets at both
  cadences: validate that each configured series exists, has its expected binary
  or hourly strike-ladder shape, and clears per-asset two-sided-quote, depth,
  open-interest, volume, spread, and data-coverage gates before it is eligible
  to trade.
- Expand manual historical collection, spot data, coverage reporting, and the
  dashboard from BTC-only to enabled registry assets. Preserve the existing
  foreground/manual collection policy; no scheduler, service, or unattended
  trading/collection process is introduced.
- Generalize event-contract backtests and strategy context assembly so each
  market uses its registry-selected underlying and cadence, running on the
  causality-safe simulation path from `kxbtc15m-validation-rebuild` (as-of
  timestamps, no incomplete-bar fills, per-fold state isolation, side-aware
  fees) rather than a per-asset execution path. Run 15-minute and hourly
  markets as separate evidence buckets, then produce asset-isolated and
  aggregate metrics; never tune or approve a strategy from pooled results that
  hide a losing asset or cadence.
- Extend the perps/event integration to registry assets only after the margin
  API confirms an active perpetual and a compatible reference index, and only
  after the asset's perpetual strategy passes the independent gate from
  `kxbtc15m-validation-rebuild`'s `perps-strategy-isolation`. A binary event
  contract is never accepted as a linear funding hedge; cross-instrument
  funding-carry hedges stay disabled until a compatible linear hedge and its
  economics are demonstrated.
- Introduce portfolio-level risk controls: per-asset entry caps, group/correlation
  caps, aggregate gross-exposure and daily-loss caps, and a default one-asset
  live rollout. BTC rules remain intact; ETH becomes the first candidate for
  paper validation, not an automatic live allocation.
- Update the dashboard and operator controls to show an asset's mode
  (`observe`, `backtest`, `paper`, or `live`), market eligibility, data coverage,
  positions, and risk allocation. **BREAKING:** former BTC-named dashboard/query
  interfaces become generic crypto-asset interfaces.

## Capabilities

### New Capabilities

- `crypto-asset-registry`: Canonical configured/discovered asset metadata,
  lifecycle mode, and validation for prediction-market, spot, and perp inputs.
- `multi-asset-portfolio-risk`: Portfolio and correlated-asset limits that
  govern admission, sizing, and promotion across crypto assets.

### Modified Capabilities

- `kalshi-market-data`: Collect, report, and qualify 15-minute and hourly data
  for enabled crypto assets instead of the BTC-only series list.
- `backtest-engine`: Bind every event market to its registered underlying and
  emit per-asset as well as aggregate results.
- `perps-trading`: Support verified non-BTC perps without weakening mandatory
  brackets, leverage caps, or compatibility checks for hedged trades.
- `scalping-strategies`: Evaluate strategies per registered asset and require
  per-asset evidence before promotion.
- `fixed-risk-sizing`: Apply fixed-risk sizing within asset and portfolio
  budgets rather than treating each asset as an independent bankroll.
- `operator-dashboard`: Replace BTC-specific coverage and status views with
  asset-aware operational views.

## Impact

- Affected code: `config/settings.py`, new registry/eligibility modules,
  `scripts/fetch_historical.py`, `scripts/archiver_loop.py`,
  `data/crypto_feeds/spot_klines.py`, `backtest/engine.py`, strategy runners,
  risk controls, margin/event adapters, dashboard queries/templates, and tests.
- Affected data: existing generic market, candle, and spot tables are reused;
  asset metadata, eligibility snapshots, and asset-level run metrics may require
  additive persistence and migration support. Historical BTC/ETH rows remain
  valid and are not rewritten.
- External dependencies: Kalshi public and authenticated margin APIs plus the
  selected CF-Benchmarks-compatible spot feeds. Runtime market discovery is
  required because Kalshi's listed assets, tickers, leverage, and liquidity can
  change.
