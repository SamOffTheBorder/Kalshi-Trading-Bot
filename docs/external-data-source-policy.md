# External data source policy

## Roles

- Binance public archives are the reproducible primary source for BTC, ETH,
  SOL, and XRP spot and USD-M futures research. Archive availability can vary
  by geography or network; an unavailable download is a failed data gate, not
  permission to substitute another feed.
- Coinbase public candles are a secondary comparison source. Incomplete
  buckets remain gaps and are never forward-filled.
- TradingView exports are operator-supplied `manual_comparison` artifacts only.
  They cannot become a primary manifest or an automated training source.
- Kalshi/BRTI or another named Kalshi settlement index is retained when a
  contract's rules require it. Exchange price data does not replace it.

## USD and stablecoins

Binance USDT-quoted prices are stored as `USDT`, never silently renamed USD.
Any later USD treatment must be a versioned, documented transform with its own
source and manifest entry. Source comparison reports flag quote incompatibility.

## Provider review before adding a vendor

Record coverage by asset/cadence, entitlement, pricing, retention rights,
attribution requirements, rate limits, historical snapshot semantics,
timestamp/availability fields, export restrictions, and a tested read-only
adapter. The vendor adapter must emit raw provenance and quality gaps before it
can be used in a manifest. No paid provider is activated by this policy.

## Retention

Raw artifacts live under ignored local `data/raw/`; SQLite stores metadata and
frozen manifests. Preserve attribution and provider retention constraints when
exporting reports. Never commit raw provider files or credentials.
