# Multi-venue paper-trading implementation inventory

This inventory is the starting boundary for `multi-venue-paper-trading`. It
does not change runtime behavior; it records which existing components are
authoritative, reusable, or scheduled for a new adapter.

| Area | Existing component | Reuse | Replacement/extension boundary |
|---|---|---|---|
| Settings and registry | `config/settings.py`, `config/crypto_registry.py` | Settings validation, asset lookup, lifecycle field | Narrow default universe to BTC/ETH/SOL/XRP; add source/admission metadata without making config alone executable authority |
| Kalshi public data | `data/kalshi/client.py`, market/candle models | Public market discovery, event quotes, official resolutions | Registry-driven four-asset discovery and freshness/source-alignment snapshots |
| Kalshi authenticated reads | BRTI source, `data/perps/kalshi_source.py`, margin client | Signed read-only BRTI, margin marks, funding, metadata | Paper guard before construction; no mutating methods in paper dependency graph |
| Binary strategy interface | `strategy/base.py`, settlement strategies | Strategy context/decision contract and HOLD audit semantics | Shared orchestrator adapter; external underlying features are inputs, never contract settlement substitutes |
| Binary paper execution | `execution/paper_broker.py` | Conservative side-aware limit fills, fees, restart recovery | Route through domain-neutral audit envelope and retain binary ledger semantics |
| Perpetual accounting | `backtest/perp_ledger.py` | PnL/funding/metrics concepts and independent promotion gate | Add persistent linear paper ledger, quotes, margin, liquidation, brackets, and live-mark loop |
| Sports research | `data/sports/*`, `scripts/capture_sports.py`, feasibility reports | Discovery, causal flow/evidence, append-only provenance, research gate | Add provider adapter and paper adapter only after exact promising report |
| Risk and halt | `risk/emergency_control.py`, drawdown/daily/consecutive guards | Existing guard semantics and dashboard control state | Add domain/asset/group/portfolio budgets and durable global halt/resume |
| Storage | `storage/models.py`, `storage/db.py`, additive migrations | Single schema, additive migration policy, existing rows | Add raw artifact, normalized external data, manifests, run/audit, and perp ledger tables |
| Website | `web/app.py`, `web/queries.py`, templates | Existing dashboard auth and control panel | Add all-domain overview and first-class Prediction/Perps/Sports status/readiness pages |
| Operator entry points | `scripts/run_paper_trading.py`, capture scripts | Foreground-only operation and bounded commands | New explicit `run_paper`/data import/report commands; preserve legacy runner as a forwarding shim |

## Data-source boundary

- Binance public spot and USD-M futures archives/API are the primary external
  history source. The adapter is read-only and stores raw artifacts plus
  checksums before normalization.
- Coinbase public candles are a secondary comparison source. Missing buckets
  remain gaps; they are never forward-filled or silently merged with Binance.
- TradingView CSV is a manual comparison artifact only. It requires operator
  symbol/interval/quote mapping and cannot satisfy a primary-data gate.
- BRTI and Kalshi margin observations remain contract-specific sources. They
  are not replaced by an external spot price when settlement rules require the
  Kalshi index or mark.
- Sports odds/evidence providers are not selected by this inventory. A provider
  adapter requires terms, rate-limit, retention, attribution, timestamp, and
  historical-coverage review before enabling it.

## Safety boundary

The current `.env` has paper mode enabled but production Kalshi environment
selection disabled (`KALSHI_USE_DEMO_ENV=False`). The new guard deliberately
refuses authenticated paper/shadow startup until the operator changes this to
the demo environment. No task in this change changes credentials or starts a
background process.
