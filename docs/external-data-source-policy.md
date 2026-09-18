# External data source policy

## Roles

- Binance public archives are the reproducible primary source for BTC, ETH,
  SOL, and XRP spot and USD-M futures research. Archive availability can vary
  by geography or network; an unavailable download is a failed data gate, not
  permission to substitute another feed. Binance is **not** eligible for BRTI
  reconstruction below: `BTCUSDT` is USDT-quoted, and Binance is not a
  documented BRTI constituent.
- Coinbase public candles are a secondary comparison source. Incomplete
  buckets remain gaps and are never forward-filled. Coinbase additionally
  holds the `constituent` role for BRTI reconstruction (below) via its
  separate USD trade-history acquisition.
- TradingView exports are operator-supplied `manual_comparison` artifacts only.
  They cannot become a primary manifest or an automated training source, and
  cannot be a composition input for index reconstruction. TradingView cannot
  serve as the training feed for this project even as a stopgap: its export
  requires a paid plan, caps at 40,000 bars (≈28 days of 1-minute data), and
  exposes no programmatic API — so it can never reach the years of history
  this project's validation gates require. This is a closed question, not one
  to be re-litigated per change.
- Kalshi/BRTI or another named Kalshi settlement index is retained when a
  contract's rules require it. Exchange price data does not replace it.

## Constituent sources and BRTI reconstruction

BRTI (the CME CF Real-Time Index) is computed once per second from the
consolidated order books of its **Constituent Platforms**: Bitstamp,
Coinbase, itBit, Kraken, Gemini, and LMAX, per the CF Benchmarks
methodology. This project registers a fourth source role, `constituent`,
distinct from `primary`/`secondary`/`manual_comparison`: it asserts that a
venue is a *documented input to a settlement index*, not merely a
reproducible or independently-sourced archive. Depth of history or
reproducibility never implies `constituent` status — it must be declared
explicitly per venue, per target index.

- **Kraken** (USD spot, complete trade history from 2013-10-06) and
  **Coinbase** (USD spot) are registered as BRTI constituents and are the
  first two composed into the synthetic proxy (`data/synthetic_brti.py`).
- **Bitstamp** (`data/bitstamp_public.py`) and **Gemini**
  (`data/gemini_public.py`) are registered as BRTI constituents with
  acquisition adapters implemented. Neither is a deep archive: Bitstamp's
  public trade endpoint only exposes a rolling minute/hour/day window with no
  pagination cursor, and Gemini's `since_tid` pagination is bounded (500
  trades/page, `MAX_TRADE_PAGES` per run) — both reach recent history, not
  years of it, the same non-deep-archive role Coinbase already has here.
  Neither is wired into the synthetic proxy's default composition yet; that
  is a follow-up, not implied by adapter existence alone.
- **itBit** and **LMAX** are not registered at all; they are materially less
  accessible for free historical data.
- Constituent membership is not fixed for all of BRTI's history. The six
  platforms above are the *current* list; an operator relying on
  reconstruction over an older window should treat the constituent set as
  a documented, versioned fact to check, not an assumption that holds
  indefinitely. `contributor_count` and the contributing-venue set are
  persisted on every reconstructed second specifically so a window built
  from two venues (today's reality) is never mistaken for one built from
  six.

The composed output carries `provenance="reconstructed_index"`, lives in a
store distinct from captured BRTI (`brti_observations`), and is never
returned by, or merged into, any read path that claims to supply captured
index data.

### Reject-but-never-admit

A dataset manifest is classified `source_native` only when **every**
partition it enumerates is source-native; any reconstructed partition, or
any partition whose provenance is missing or unrecognized, classifies the
whole manifest `reconstructed` (fail-closed — see `data/manifests.py`).

A run against a `reconstructed` manifest is diagnostic-only. The asymmetry
is deliberate: a strategy that **loses** money across years of constituent
history is falsified cheaply and credibly — proxy error is not what killed
it, so that rejection is directly actionable. A strategy that **wins** on
reconstructed data has shown only that it wins on a series that is not the
settlement index; a diagnostic-only *passing* result is reported with an
explicit "requires captured-BRTI validation" status and never satisfies a
promotion criterion (`backtest/promotion_gate.py`). The same rule is
enforced mechanically at the paper-run boundary: `execution/orchestrator.py`
refuses fills (never decision recording) for an asset whose frozen admission
report is backed by a `reconstructed` manifest, with reason
`reconstructed_data_not_admissible`.

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
