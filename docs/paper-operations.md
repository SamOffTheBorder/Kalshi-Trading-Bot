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

To freeze currently captured inputs for one asset, run:

```text
python scripts/freeze_manifest.py --asset BTC --source spot --source brti \
  --output reports/btc-manifest.json
```

The command computes observed bounds and partition provenance, then uses the
idempotent manifest store. Reconstructed data remains explicitly non-native
and cannot authorize a fill.

Perp discovery is a separate foreground, read-only pass over Kalshi's
authenticated `/margin/markets/{ticker}` endpoint:

```text
python scripts/discover_crypto_perps.py --output reports/perp-discovery.json
```

## Strategy lab and multiple paper accounts

`scripts/run_paper.py --domain prediction --strategy <id>` runs one paper
account against a named strategy. `scripts/run_strategy_lab.py --spec
lab.json` runs several at once — each account a full paper run with its own
`paper_run_id`, strategy, config id, asset set, bankroll, and mode. The
**Strategy lab** dashboard page compares recent runs side by side.

### The registry and gate status

The CLI accepts `--domain sports`, but sports remains gated until the
feasibility work owned by `sports-market-feasibility` and
`sports-evidence-and-flow-research` produces a passing `research_promising`
report. Wiring the adapter does not loosen that gate.

`src/kalshi_bot/strategy/registry.py` is the one place a `strategy_id` maps
to a constructed strategy, its frozen config, and its **gate status**:

| id | gate status | basis |
|---|---|---|
| `hold` | `never_gated` | the default; never enters |
| `trend_scalp` | `gate_failed` | v2 §8.4: 0 walk-forward test trades vs the ≥200-trade gate |
| `level_break` | `gate_failed` | v2 §8.4: same |
| `settlement_prob` | `never_gated` | built in kxbtc15m-validation-rebuild; data-blocked on captured BRTI |
| `settlement_trend` | `never_gated` | kxbtc15m-validation-rebuild §4.4; "NOT presumed to be an edge" |
| `crypto_mispricing` | `parked` | v2 "Removed Capabilities": no demonstrated directional edge |

An unknown `strategy_id` is refused at preflight (`unknown_strategy_id`)
before any run row is written. Gate status is persisted on every `PaperRun`
and shown on every run row in the dashboard. **A paper result never changes
a strategy's gate status** — it is an input to a future gate decision, not a
substitute for one. A `gate_failed` or `never_gated` strategy is runnable in
the lab for observation; the promotion gate (`backtest/promotion_gate.py`)
is unchanged and still refuses it.

### Why the lab has no backtest mode

The KXBTC15M walk-forward holdout for `trend_scalp` and `level_break` has
already been used — both failed the pre-registered 2026-08-18 gate on trade
count. Re-running them against that same holdout with new configs is tuning
into a spent holdout, the exact discipline failure that made Phase 1's
results untrustworthy (its test window was peeked four times). New backtest
evidence for those strategies waits for genuinely new data and a new
pre-registered split, as a separate change. The lab runs **forward, on live
paper data**, where every observation is out-of-sample because it did not
exist when the config was frozen.

### Per-account isolation

Each account gets its own bankroll and capital ledger; sizing for one
account never observes another's cash, positions, or equity. This is not
just tidy: v2 §8.3's second sizing bug was a shared-ledger failure —
concurrent correlated entries each read the same pre-batch equity and each
believed the whole bankroll was available, producing a phantom 57.7%
drawdown. Separate accounts that shared capital would reproduce that bug at
a coarser granularity. `MAX_ACCOUNTS` caps the fan-out and
`poll_interval_seconds` is held to a ≥10s floor so several accounts polling
Kalshi's public endpoints do not defeat the client's 429 backoff.

The lab is foreground-only — no scheduler, no daemon, no auto-restart (the
standing O1 decision). One Ctrl+C forwards a clean stop to every account.

## Halt, reconciliation, rollback

Use the dashboard kill control to halt entries, then stop the relevant local
process. A later run must reconcile open paper state before new entries. A
restart is not a resume authorization. To roll back an experiment, retain its
immutable manifest/report and select a prior config; do not rewrite captured
history or remove audit events.
