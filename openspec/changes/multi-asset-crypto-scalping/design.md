## Context

v2 has sound generic storage tables (`KalshiMarket`, `Candle`, and
`SpotCandle`), but its operational paths are BTC-specific: historical scripts
use three BTC series, dashboard coverage is `BTC_SERIES`, and
`BacktestEngine.SERIES_SYMBOL` is a module constant. ETH mapping exists only as
legacy data/backtest entries and is deliberately excluded from the current
manual collector. The strategies themselves consume an asset-agnostic
`StrategyContext`, which is a useful seam for expansion.

Kalshi currently exposes 15-minute up/down series and hourly crypto markets for
BTC, ETH, SOL, XRP, DOGE, BNB, HYPE, NEAR, and ZEC. Its available perp universe is different and
can change; its common subset is the only candidate set for event/perp hedges.
Existing evidence established that a quoted ticker is not automatically
tradeable: the prior BTC ladder backtest filled unquoted/empty markets. This
design preserves manual, foreground data collection and all v2 stop, leverage,
and paper-to-live gates.

## Goals / Non-Goals

**Goals:**

- Make the selected crypto universe and its 15-minute/hourly event cadences
  data-driven and centrally validated.
- Add ETH first while allowing the remaining screenshot assets to collect data
  in observation mode without gaining trading permission.
- Apply liveness and per-asset evidence gates before a market can enter a
  backtest, paper, or live path.
- Ensure aggregate exposure is safe when highly correlated crypto assets signal
  together, and make asset-level evidence visible to the operator.
- Support cross-instrument strategies only after runtime verification of both
  instruments and their settlement/reference-index compatibility.

**Non-Goals:**

- No live order enablement for every discovered asset, no fixed claim that a
  currently listed Kalshi asset will remain listed, and no automatic promotion
  based solely on volume.
- No new alpha strategy, re-optimization on pooled multi-asset results, market
  making, external exchange execution, or new unattended process.
- No assumption that prediction-market and perpetual ticker spelling, contract
  multiplier, maximum leverage, funding convention, or reference index is
  shared across assets.

## Decisions

### D1 — Use an explicit registry with discovery as validation, not discovery as authorization

Create a typed `CryptoAssetConfig`/registry entry keyed by a stable asset ID
(for example `ETH`). It contains display name, spot symbol, an event-series map
keyed by cadence (`15m` and `60m`), expected contract shape for each series,
optional perp lookup identity, and lifecycle mode per instrument/cadence. The
shipped starting registry is:

| Asset group | Assets | Initial mode | Instruments permitted after validation |
|---|---|---:|---|
| Established | BTC | existing mode | existing event/perp scope |
| First expansion | ETH | `backtest` | 15m and hourly events; perp only after separate paper gate |
| Observation universe | SOL, XRP, DOGE, BNB, HYPE, NEAR, ZEC | `observe` | archive/report both cadences when listed |
| Perp-only candidate | LINK | `observe` when discovered | perp data only; no synthetic event hedge |

At startup and on each explicit/manual refresh, query Kalshi to confirm each
configured 15-minute and hourly event series exists and inspect active markets.
Authenticated margin
market discovery separately confirms any perp. A mismatch disables only the
affected instrument and surfaces a reason; it never falls back to a guessed
ticker. This approach is preferred over hard-coded series constants because
the venue's listed set changes, and over unrestricted auto-discovery because a
new or malformed series must not acquire trading authority.

### D2 — Separate observation, research, and execution permissions

Every asset has a monotonic lifecycle: `observe` → `backtest` → `paper` →
`live`. Collection and dashboard visibility require `observe`; backtests require
`backtest`; an execution adapter independently checks `paper`/`live` and the
existing global paper/live confirmation. Promotion is a deliberate config change
backed by a recorded eligibility snapshot and per-asset gate results. A
demotion is immediate and stops new entries while ordinary exit protection
remains active.

This is preferred to a single enabled boolean: it lets the project gather the
data the user wants without treating data availability as proof of an edge.

### D3 — Qualify markets at three levels

1. **Series contract:** public discovery confirms configured cadence and expected
   shape: 15-minute single-binary markets or hourly binary/strike-ladder markets
   as declared by the registry.
2. **Market liveness:** an open market has both sides quoted, acceptable spread,
   minimum best-level/depth liquidity, and minimum recent volume/open interest.
3. **Asset eligibility:** the series has sufficient archival coverage and gap
   quality, and the asset-specific strategy test/paper metrics clear a frozen
   gate.

All per-asset backtests execute on the causality-safe simulation path defined
by `kxbtc15m-validation-rebuild` (`causal-strategy-validation`): as-of feature
timestamps, no incomplete-bar fills, fresh broker/guard state per fold, and
side-aware YES/NO plus both-leg fee accounting. This change adds the registry
and per-asset budgeting on top of that path; it does not define its own
execution model, and legacy pre-rebuild v2 backtest numbers do not satisfy any
asset's gate.

The existing `is_live_quote` remains a final per-candle guard in backtests; it
is strengthened by configurable asset thresholds rather than replaced. Default
thresholds are intentionally fail-closed and belong in configuration, so an
operator cannot enable an asset just because the ticker was found. Exact
threshold values are initially calibration inputs, recorded alongside every
eligibility decision; the implementation must not invent favorable defaults.

### D4 — Generalize mappings at the boundary, keep strategies asset-neutral

Replace `SERIES_SYMBOL` with a registry lookup passed into the backtest/live
context builder. The builder supplies the asset ID and event cadence in
`StrategyContext.extras` and selects only the registered spot history. Strategies remain pure and do not
fetch or identify assets themselves. Each backtest run stores the immutable
registry snapshot, selected assets, cadences, evaluation settings, and
asset/cadence-level metrics. Aggregate performance is supplemental; it cannot
pass the gate if an asset's own test segment or either selected cadence fails.

This is preferred to strategy subclasses such as `EthTrendScalp`: the signal
logic is the same class of hypothesis, while its evidence, liquidity, and risk
budget must be evaluated separately.

### D5 — Make risk hierarchical and correlation-aware

Use one account equity base, allocating in this order:

`global emergency/daily limits → crypto portfolio gross-risk cap → correlation
group cap → per-asset cap → existing fixed-R size and exchange constraints`.

All configured crypto assets initially share a single `major-crypto` correlation
group. A group has a total risk/exposure ceiling and a maximum number of open
asset directions. BTC and ETH do not receive independent full bankrolls.
Existing per-position 1–2% fixed-R limits, 2x default/3x hard perps leverage
ceiling, daily-loss halt, and server-side brackets continue unchanged. The
implementation records which gate rejected an entry.

### D6 — Cross-instrument compatibility is an invariant

Funding-carry and any future event/perp hedge require a registry relationship
that has been verified at runtime: active event instrument, active margin
instrument, matching asset, compatible CF Benchmarks reference/settlement index,
and contract/multiplier metadata sufficient to calculate a conservative hedge.
Runtime verification is necessary but not sufficient: a binary event contract is
never accepted as a linear funding hedge, so funding-carry stays disabled until
`kxbtc15m-validation-rebuild`'s `perps-strategy-isolation` gate is met with a
demonstrated compatible linear hedge, its rebalance cadence, complete fees, and
residual basis risk. If any condition is missing or stale, the strategy returns
`HOLD` with a compatibility reason. Non-BTC perp strategies promote only through
that independent perp gate, never off an event-contract strategy's results.
Prediction-only assets (initially BNB, NEAR, and ZEC) remain eligible only for
independently validated event strategies. Perp-only LINK cannot be paired with a
synthetic event side.

### D7 — Persist decisions and show the operator both unknowns and risk

Add additive tables or JSON snapshot fields for registry versions, discovery
results, eligibility checks, and asset-level metrics. Do not mutate historical
BTC/ETH rows. Queries and templates become generic `crypto_assets`/coverage
views; they display asset mode, current discovery state, data window/gaps,
latest qualification reason, group exposure, and whether an instrument is
event-only, perp-only, or pair-compatible. Failure to obtain a snapshot renders
an explicit stale/unavailable state, never stale data as live.

## Risks / Trade-offs

- **Low-liquidity alt markets or one cadence look available but cannot absorb the intended size**
  → require book/depth thresholds, observed-fill evidence, and `observe` mode
  by default.
- **Correlated signals multiply losses during market-wide moves** → one shared
  correlation group and portfolio cap precede every asset's own sizing.
- **Pooled backtests hide asset-specific failure** → require frozen,
  asset-isolated OOS metrics and show them alongside aggregate results.
- **Venue contract/ticker/index changes** → validate dynamically and fail closed;
  registry configuration is reviewed rather than self-authorizing.
- **More series make manual collection slower and gaps more likely** → bounded
  per-series time budgets, per-asset coverage reports, and manual operator
  visibility; no deviation from the accepted no-background-process policy.
- **Spot sources do not support every alt with equivalent quality** → registry
  validation requires explicit supported feed mappings; unsupported assets stay
  in observation until a compatible source is selected and tested.
- **Schema additions are not applied by `create_all_tables` to existing SQLite
  tables** → use an explicit, idempotent migration path and test both populated
  and fresh databases.

## Migration Plan

1. Add registry/configuration, migrations, and tests with all new assets in
   `observe` except ETH in `backtest` for both configured cadences; retain BTC
   behavior exactly.
2. Run a manual discovery/collection pass and generate data-coverage and
   liquidity snapshots. Resolve unsupported feed/index mappings before moving an
   asset past observation.
3. Run frozen per-asset backtests. Do not inspect pooled results as a substitute
   for each asset's test segment.
4. Promote ETH only to paper after its own event contract gate clears; promote a
   compatible ETH perp only after its bracket and two-instrument hedge tests.
5. Promote each remaining asset one at a time after the same evidence and
   portfolio-risk review. Live promotion remains subject to v2's existing gates.

Rollback is configuration-first: demote an asset to `observe`, stop new entries,
and retain/close positions through existing emergency controls and brackets.
Registry snapshots and historical records remain for audit. If a migration fails,
restore the database backup before retrying; no data rewrite is part of this
change.

## Open Questions

- What per-asset and per-cadence minimums (depth, OI, recent volume, spread,
  coverage duration, maximum gap count) will be adopted after observing live
  books? The proposal deliberately makes them explicit configuration rather
  than invented values.
- Which supported CF-Benchmarks-compatible spot feeds will be used for SOL,
  XRP, DOGE, BNB, HYPE, NEAR, ZEC, and LINK when Coinbase/Kraken do not jointly
  cover an asset?
- Should BTC and ETH remain one `major-crypto` group permanently, or can a
  measured rolling-correlation policy create separate groups later? This change
  starts conservatively with one group.
- What evidence duration/trade count is sufficient for per-asset paper
  promotion? The implementation must make this a recorded gate, but the owner
  must approve the numerical threshold before live use.
