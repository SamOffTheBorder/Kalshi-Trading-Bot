# Paper operations

Start the local dashboard with `start_dashboard.bat`, then use **Data &
capture** to start or stop capture. Use **Operations** for allowlisted tests,
validation, and the paper-engine control. The dashboard binds to localhost.

## Safety and promotion

All authenticated paper reads require `PAPER_TRADING=true` and
`KALSHI_USE_DEMO_ENV=true`. A configured asset is not paper-admitted merely
because it appears on the dashboard: it needs fresh discovery, source
alignment, a frozen manifest, an applicable risk-policy pass, and its
domain-specific evidence. Sports remains disabled unless its research report
passes the registered prerequisite.

## Data storage and sources

Local raw artifacts are under ignored `data/raw/`; manifests pin provenance.
See `external-data-source-policy.md` for Binance, Coinbase, TradingView, and
settlement-index roles. Do not copy secrets into reports or raw datasets.

## Halt, reconciliation, rollback

Use the dashboard kill control to halt entries, then stop the relevant local
process. A later run must reconcile open paper state before new entries. A
restart is not a resume authorization. To roll back an experiment, retain its
immutable manifest/report and select a prior config; do not rewrite captured
history or remove audit events.
