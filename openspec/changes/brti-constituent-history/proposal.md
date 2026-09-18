## Why

Strategy research for KXBTC15M is starved of history. The only true BRTI feed
this project can reach is Kalshi's authenticated CF Benchmarks passthrough,
which is a *live* endpoint: it yields readings from the moment capture starts
and nothing before it. The local ledger currently holds zero rows, so every
walk-forward split, volatility estimate, and promotion gate is being asked to
run on data that does not exist.

The existing external-data lake fills part of this hole with Binance
`BTCUSDT`, but Binance is a poor stand-in for BRTI specifically: it is
USDT-quoted rather than USD, and it is **not one of the index's inputs**.

BRTI is not a separate market that merely correlates with spot venues. Per the
CME CF Real-Time Index methodology it is computed once per second from the
consolidated **order books** of its Constituent Platforms — Bitstamp,
Coinbase, itBit, Kraken, Gemini, and LMAX. The constituents are the index's
inputs, not its cousins. That makes a far stronger claim available than
"similar shape": a series built from constituent USD books is an
*approximation of the actual index input*, and its error against real BRTI is
measurable rather than assumed.

Kraken publishes complete USD trade history back to 2013-10-06 for free, and
Coinbase publishes USD history back to 2015 — years of constituent data, at no
cost, versus the ~28 days a TradingView Ultimate export would yield. This
change acquires that history and composes it into an explicitly-labelled
BRTI proxy whose only sanctioned use is **falsifying** strategies cheaply.

The safety problem this creates is the reason for the change's other half. A
reconstructed index that silently reaches a promotion gate would let a
strategy be admitted to paper trading on evidence that was never BRTI. The
project's existing rule — a research result is never an execution
authorization — needs a mechanical enforcement point here, not a convention.

## What Changes

- Add **Kraken** and **Coinbase** USD spot history as first-class primary
  sources for BTC/ETH/SOL/XRP, alongside the existing Binance mappings. Kraken
  is the deepest free constituent archive (complete trade history from
  2013-10-06); Coinbase is the second constituent and the largest US venue.
  Both are USD-quoted, unlike the current `BTCUSDT` mappings.
- Extend the source-role vocabulary with **`constituent`**: a source that is a
  documented input to a settlement index, as distinct from `primary` (a
  reproducible archive) and `manual_comparison`. Bitstamp and Gemini are
  registered as constituents behind an adapter seam but are not required for
  the first composition.
- Add a **synthetic BRTI composer** that blends constituent USD series into a
  1-second reference series carrying `provenance="reconstructed_index"`. The
  composer never emits a value labelled BRTI, never writes to
  `brti_observations`, and records which constituents contributed to every
  interval so a thin-coverage window is visible rather than smoothed away.
- Add a **reconstruction-error report**: when a window has both true captured
  BRTI and synthetic coverage, compute the divergence at the timescale the
  strategy actually resolves on — the 60-second mean that
  `signals/settlement_window.py` uses — not merely tick-level correlation. The
  measured error is written into the dataset manifest.
- **Enforce the provenance boundary mechanically.** A dataset manifest
  containing any `reconstructed_index` partition is marked diagnostic-only. A
  diagnostic-only manifest may drive training, walk-forward research, and
  strategy *rejection*, but SHALL NOT satisfy an admission report or promote an
  asset's lifecycle to `paper`. The paper-run preflight refuses a frozen report
  whose manifest is diagnostic-only.
- Add foreground operator commands to download, verify, normalize, and compose
  constituent history, and to print coverage and reconstruction error.

**Non-goals.** No paid data purchase. No TradingView automation — the existing
`manual_comparison` boundary in `data/tradingview_import.py` stands unchanged,
and this change documents why it can never be the training feed (export is
paywalled and caps at 40,000 bars ≈ 28 days of 1-minute data). No live-order
path. No scheduler or background service.

## Capabilities

### New Capabilities

- `synthetic-index-reconstruction`: Composition of constituent-venue USD series
  into a labelled BRTI proxy, its coverage accounting, and the measurement of
  its error against true captured BRTI at the strategy's resolution timescale.

### Modified Capabilities

- `external-market-data-lake`: Adds the `constituent` source role, Kraken and
  Coinbase USD acquisition adapters, and the requirement that reconstructed
  partitions are labelled and never merged into a source-native series.
- `underlying-strategy-validation`: Adds the diagnostic-only manifest
  classification and the rule that reconstructed data may eliminate a strategy
  but never admit one.

## Impact

- Affected code: `data/external_sources.py` (source roles, Kraken/Coinbase
  mappings), new `data/kraken_public.py` and `data/coinbase_public.py`
  acquisition adapters, new `data/synthetic_brti.py` composer,
  `data/manifests.py` (diagnostic-only flag), `data/quality_policy.py`
  (reconstruction-error threshold), `execution/orchestrator.py` (preflight
  refuses a diagnostic-only frozen report), `backtest/promotion_gate.py`, web
  queries/templates for coverage display, and scripts for the new commands.
- Affected data: additive raw artifacts and normalized partitions for Kraken
  and Coinbase USD; a new reconstructed-index partition family; manifest
  fields for provenance class and measured reconstruction error. Existing
  Kalshi, BRTI, and Binance records stay immutable and keep their original
  provenance.
- External systems: Kraken's published historical download endpoints and
  Coinbase's public candle/trade API. Both are free and public; neither is an
  execution venue in this change. Kalshi's authenticated BRTI passthrough is
  still required to *measure* reconstruction error, so that measurement stays
  unavailable until credentials are configured — and the change treats an
  unmeasured proxy as unvalidated rather than assumed-good.
- Safety: `PAPER_TRADING=true` remains mandatory. The new boundary is
  fail-closed — an unlabelled or unmeasured reconstruction is treated as
  diagnostic-only, so the failure mode of forgetting to classify a manifest
  blocks promotion rather than permitting it.
