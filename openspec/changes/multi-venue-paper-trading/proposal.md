## Why

The bot has a safe but narrow BTC prediction-market paper loop, read-only
perpetual capture, and sports feasibility research; it does not yet provide
one safe, comparable paper-trading system across prediction markets,
perpetuals, and sports.  Its strategy validation also relies too heavily on
Kalshi/BRTI-specific history, which is insufficient to train and falsify
underlying-market signals for BTC, ETH, SOL, and XRP.

This change creates a staged, evidence-led route from reproducible external
market data to paper trading for those four assets and a separately-gated
sports pilot. It preserves the rule that a research result is never an
execution authorization.

## What Changes

- Establish the active crypto universe as **BTC, ETH, SOL, and XRP**. Remove
  every other asset from default collection, research, dashboard, and paper
  admission. An asset remains non-tradable until its configured venue,
  underlying data, discovery snapshot, and asset-specific evidence gate pass.
- Add a versioned external-market-data lake for spot and perpetual reference
  data. The default historical source is exchange-native, downloadable,
  checksum-verifiable Binance public data (spot and USD-M futures); Coinbase
  is an independently captured secondary validation source. TradingView CSV
  import is supported only as a manual, non-authoritative comparison source:
  it is useful for visual inspection but cannot be a reproducible automated
  training feed.
- Import, normalize, validate, and retain raw provenance for 1-minute and
  coarser OHLCV, aggregate trades, funding, and, when captured live, L2/book
  observations. Enforce source-time and availability-time rules, dataset
  fingerprints, symbol mapping, integrity checks, gap reports, and immutable
  training/holdout manifests. Never substitute an underlying exchange price
  for a Kalshi settlement index when evaluating settlement accuracy.
- Build underlying-data backtests for BTC, ETH, SOL, and XRP using chronological
  walk-forward splits, purged embargoes, per-asset results, fees, slippage,
  funding, liquidity, and train/validation/test isolation. Prediction-market
  strategies must additionally be evaluated against the actual Kalshi market
  contract, its settlement terms, and time-available quote data; external
  data is a feature source, not a shortcut for binary-contract PnL.
- Replace the BTC-only runner with a registry-driven, foreground-only paper
  orchestrator. It persists every decision, quote, fill, position, rejection,
  halt, and settlement with a domain-specific ledger and never routes an order
  to a live Kalshi endpoint.
- Add a dedicated perpetual paper broker for linear contracts: side-aware
  mark/bid/ask fills, contract multiplier and minimum size, margin/equity,
  leverage caps, realized and estimated funding, liquidation-distance
  simulation, brackets, mark-to-market, settlement/restart recovery, and
  independent promotion metrics. Binary prediction contracts are never used
  as a linear hedge unless a future compatibility gate proves the relationship.
- Add a sports paper-trading candidate path only after existing feasibility
  research produces sufficient causal capture and a pre-registered
  `research_promising` result. It models binary contract fills, official
  settlement, sport/game/market eligibility, stale data, and external evidence
  provenance. Copy trading is explicitly unsupported unless a lawful,
  attributable public feed is separately approved.
- Provide dashboard and operator views for prediction markets, perpetuals,
  sports, the four-asset universe, data freshness/coverage, source provenance,
  candidate status, positions, domain-separated PnL, correlation exposure,
  risk guard state, and explicit reasons an entry is blocked.
- Add foreground operator commands for import, discovery, paper runs,
  stopping/resuming, reports, and verification. **BREAKING:** the default
  crypto registry and dashboard views become BTC/ETH/SOL/XRP-only; the legacy
  BTC-only paper-run command is replaced by a domain/asset-selecting command.

## Capabilities

### New Capabilities

- `external-market-data-lake`: Provenance-preserving acquisition, manual
  import, normalization, validation, and reproducible manifests for external
  crypto spot/perpetual market data.
- `underlying-strategy-validation`: Per-asset, walk-forward training and
  backtesting against external underlying data while retaining contract-aware
  validation for Kalshi prediction markets.
- `paper-trading-orchestrator`: Foreground-only, registry-driven orchestration
  of data, strategy, risk, simulated execution, persistence, and recovery.
- `perpetual-paper-execution`: Linear perpetual simulation with margin,
  funding, liquidation, brackets, and independent promotion evidence.
- `sports-paper-execution`: Evidence-gated paper execution for eligible sports
  binary markets after feasibility validation; no live execution.
- `cross-domain-risk-governance`: Domain, asset, correlation-group, portfolio,
  freshness, and emergency-halt controls that prevent one paper strategy from
  masking another's risk or readiness.
- `paper-trading-operations`: Dashboard and operator workflows for data
  coverage, paper-run health, ledger reconciliation, reports, and safe stop/
  resume control.

### Modified Capabilities

None. This repository has no living `openspec/specs/` capabilities to modify;
the new specifications formalize behavior currently spread across open changes.

## Impact

- Affected code: crypto registry/settings, storage migrations/models, external
  data adapters/importers, historical and live capture commands, strategy and
  backtest engines, event and perpetual paper brokers, risk controls, web
  queries/templates, reports, and test fixtures.
- Affected data: additive raw-source manifests, normalized underlying bars/
  trades/books, source and availability timestamps, data-quality/gap records,
  paper ledgers, and promotion reports. Existing Kalshi and BRTI records stay
  immutable and retain their original provenance.
- External systems: public Binance archive/API as the primary external history;
  Coinbase public data as a cross-source check; TradingView CSV through a
  manual import boundary only; Kalshi public and authenticated read-only margin
  APIs; an operator-approved sports-odds/evidence provider only after legal,
  cost, rate-limit, and historical-coverage review.
- Safety: `PAPER_TRADING=true` remains mandatory; all production order methods
  stay blocked; `KALSHI_USE_DEMO_ENV=true` becomes required by paper commands
  that require authenticated Kalshi data; no scheduler, background service,
  copy-trading integration, paid-provider purchase, or live-capital route is
  introduced.
