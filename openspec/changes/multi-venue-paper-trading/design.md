## Context

The repository currently has three partially independent paths:

- `scripts/run_paper_trading.py` can paper trade one BTC 15-minute Kalshi
  event series with a binary-contract broker and BRTI observations.
- Kalshi margin clients and capture code can discover/capture crypto perpetual
  marks and funding, while `backtest/perp_ledger.py` provides accounting only;
  no perpetual paper execution loop exists.
- Sports discovery, flow, evidence, and feasibility code is research-only and
  has no paper-execution authorization.

The default registry contains assets beyond the intended scope and assigns
different lifecycle states. The intended active universe is exactly BTC, ETH,
SOL, and XRP. Existing BRTI observations remain useful because Kalshi contract
settlement may reference that index, but BRTI alone cannot provide broad,
portable underlying spot/perpetual features or independent validation.

The operator wants real historical and live data suitable for training and
backtesting, but all implementation must preserve causal availability,
repeatability, paper-only execution, and foreground operator control. Existing
worktree changes and open OpenSpec changes are user-owned context: this change
integrates with them but neither overwrites their reports nor treats incomplete
evidence as a pass.

External-data findings inform the design:

- [Binance Public Data](https://github.com/binance/binance-public-data) offers
  daily/monthly downloadable spot and USD-M futures archives, describes the
  bar/trade schemas, and publishes sidecar checksums. It is the primary
  reproducible history source, subject to geographic/network availability.
- [Coinbase product candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles)
  are a secondary independent check, not a sole record: Coinbase documents
  that historical rate buckets can be incomplete.
- [TradingView chart export](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/)
  exports the data currently loaded in a chart. It is therefore a manual
  comparison/import route, not a versioned programmatic data feed. Its replay
  paper results are also session-local rather than a source of record.
- A sports-odds provider must be selected only after entitlement review. For
  example, [The Odds API](https://the-odds-api.com/docs/) advertises current
  and historical odds snapshots, but coverage, timestamps, price, permitted
  storage, and attribution must be recorded in an adapter contract before use.

## Goals / Non-Goals

**Goals:**

- Safely prepare a single paper-only system for Kalshi prediction markets,
  Kalshi crypto perpetuals, and eligible sports markets.
- Make BTC, ETH, SOL, and XRP the only default crypto assets; require separate
  discovery, data, strategy, and risk approval for every asset/domain pair.
- Build reproducible underlying-market datasets from raw downloads and
  point-in-time captures, rather than deriving all features from BRTI.
- Keep prediction-market tests contract-aware: source/settlement alignment,
  decision-time Kalshi quotes, side-aware fees, fills, and actual resolution
  remain required even when model features come from external data.
- Establish isolated paper ledgers, metrics, risk budgets, restart behavior,
  reconciliation, and promotion gates for binary events, perpetuals, and
  sports.
- Let the dashboard explain *why* a market/asset is blocked, not merely show a
  favourable strategy signal.

**Non-Goals:**

- Live orders, live capital, unattended daemons, automatic restart/scheduling,
  or any removal of the existing live-order interlock.
- Scraping or reverse-engineering TradingView, copying another trader's orders,
  importing private trade signals, or using an LLM as an execution authority.
- Treating a Binance/other-exchange price as the Kalshi contract settlement
  price, assuming USDT equals USD without recording the choice, or pooling
  asset/domain performance to hide a failed component.
- Sports futures, parlays, player props, in-play paper trading, exchange
  betting, or any sports execution before the existing feasibility gate passes.
- Buying a data subscription, transmitting private data to a provider, or
  changing user credentials without an explicit subsequent operator action.

## Decisions

### 1. Use a source-of-record hierarchy, not one universal price feed

**Decision.** Store raw data and provenance from several sources, with an
explicit primary/secondary role per use case:

| Use | Primary source | Secondary/check | Contract-specific source |
|---|---|---|---|
| Crypto spot features | Binance public spot archive/API | Coinbase public candles | Kalshi BRTI/index only where settlement requires it |
| Crypto perp features/funding | Binance USD-M archive/API | Coinbase/Kraken spot sanity check | Kalshi margin marks/funding for Kalshi-perp execution |
| Prediction market quotes/resolution | Kalshi public API/capture | None substitutes it | Kalshi rules and settlement index |
| Sports probability/evidence | Approved provider adapter | Independent provider where licensed | Kalshi market/rules/settlement |

The source identity, exchange symbol, quote currency, raw checksum/content
hash, API/archive URL, retrieval time, observed time, availability time,
parser version, and transformation version SHALL accompany every derived
dataset. A dataset manifest pins exact raw artifact hashes and a code/config
fingerprint before a training or backtest run starts.

**Rationale.** Exchange-native archives are automatable and reproducible;
cross-source checks reveal outages, symbol changes, bad parsing, or a source
specific anomaly. Kalshi contract data is indispensable for modelling binary
execution and resolution. TradingView does not offer the required automation
and provenance guarantee.

**Alternatives considered.**

- *TradingView as the default feed*: rejected because its documented chart CSV
  export is bounded by loaded chart data and is manual; it is retained only as
  an operator-supplied comparison artifact.
- *BRTI-only*: rejected because it constrains feature/sample coverage and
  offers no independent underlying venue history; retained for settlement
  windows that explicitly use it.
- *A paid consolidated provider from day one*: deferred. It can be added behind
  the adapter/manifest interface after entitlement/cost approval without
  changing research semantics.

### 2. Normalize data but retain raw truth and source semantics

**Decision.** Add immutable raw-artifact and normalized-observation storage.
Raw artifacts are content-addressed files plus metadata. Normalized records use
UTC epoch milliseconds, `observed_at`, `available_at`, `retrieved_at`, source,
instrument identifier, quote currency, and a quality status. Bars include open
and close intervals; a bar is unusable for a decision until `available_at` and
its close time have passed. Aggregate trades retain aggressor/maker direction
when supplied, but unknown direction stays unknown.

No process overwrites an artifact or normalizes missing points by forward-fill.
Duplicate idempotency keys comprise source, venue symbol, observation type,
observed time, sequence/trade identifier when present, and parser version.
The importer produces a machine-readable coverage/gap report. A source change,
symbol migration, timestamp-unit migration, checksum mismatch, or broken
ordering produces a rejected artifact and fails closed for dependent runs.

**Rationale.** Feature reproducibility and leakage prevention require both the
data value and the point at which the process could know it. Keeping raw and
normalized forms permits parsers to improve without corrupting earlier
evidence.

**Alternative considered.** A single mutable parquet/SQLite table is simpler,
but it cannot reconstruct a report after a provider revises an archive or a
parser bug is fixed.

### 3. Separate underlying-model evidence from instrument execution evidence

**Decision.** Each candidate has two or three mandatory, independently
reported layers:

1. **Underlying layer**: BTC/ETH/SOL/XRP spot or futures model evaluated on
   chronological walk-forward data with feature availability at decision time.
2. **Instrument layer**: either prediction contract or perpetual execution
   simulation on the venue's own contemporaneous market data, economics, and
   settlement rules.
3. **Cross-instrument layer** (only if proposed): basis/hedge compatibility,
   same asset/reference index, current metadata, sizing residual, and full
   costs. A binary contract never qualifies as a linear hedge by label alone.

For prediction contracts, features may use external data but target labels,
quote time, contract close/settlement windows, spreads, fees, size, and outcome
must come from Kalshi. A `source_alignment` verdict reports whether external
price, BRTI, and contract settlement definition are compatible. Incompatible or
unknown alignment blocks entry and marks the candidate diagnostic only.

For perps, a separate mark-to-market ledger uses the actual Kalshi perp mark,
bid/ask, multiplier, funding, margin and liquidation data. Underlying price
history is not a replacement for these execution fields.

**Rationale.** A model can predict an exchange price and still fail to price a
Kalshi binary or to survive perpetual spreads/funding. Separate ledgers prevent
misleading aggregate PnL.

### 4. Enforce chronological experimental design

**Decision.** The data/validation package supplies fixed configs for 1-minute,
15-minute, and 60-minute models and requires:

- train/validation/test order in time, rolling or expanding walk-forward
  folds, and a purge/embargo equal to the maximum feature lookback plus target
  horizon;
- no use of an incomplete bar, post-decision trade, later-revised artifact, or
  unavailable funding/odds/evidence value;
- frozen model, feature, raw-manifest, execution assumptions, risk policy,
  code revision, and random seed before the held-out segment is evaluated;
- per-asset, per-cadence, per-domain metrics plus a *worst component* rule:
  aggregate success cannot promote a component that individually fails;
- baselines: market/hold, simple momentum or naïve probability baseline, and
  a no-trade result after fees; and
- bootstrap/confidence intervals, calibration where a probability is emitted,
  and explicit sample/coverage minimums.

Training receives no LLM/web output unless it is a captured, timestamped,
allowlisted evidence record; the LLM can summarize evidence but cannot label
outcomes, choose a trade, change a threshold, or call a broker.

### 5. Define domain-specific simulated execution behind one orchestrator

**Decision.** `PaperRun` coordinates discovery/capture, as-of feature creation,
strategy evaluation, risk admission, a domain adapter, persistence, and report
emission. It accepts `--domain prediction|perp|sports`, `--assets BTC,ETH,SOL,XRP`,
and bounded `--duration`, runs in the foreground, and exits cleanly on
Ctrl+C/SIGTERM. It does not start itself or another process.

Domain adapters share an envelope (`Decision`, `RiskDecision`, `PaperOrder`,
`PaperFill`, `PaperPosition`, `PaperEvent`) but not price/settlement semantics:

- **Prediction/Sports binary adapter**: YES/NO, side-aware top-of-book
  marketable limits, documented fees, conservative observable liquidity cap,
  actual official resolution, stale quote rejection, and no fabricated maker
  fills.
- **Perp adapter**: long/short signed quantity, bid/ask execution, multiplier,
  maker/taker schedule, initial/maintenance margin, leverage at or below 2x
  default/3x hard ceiling, funding cash flows, mark-to-market equity,
  liquidation distance, brackets, and forced-close simulation. It has its own
  `PerpPaperPosition`/ledger, not `SimulatedTrade`'s binary semantics.
- **Sports adapter**: disabled by default and refuses startup unless the
  feasibility report, market-rule record, provider provenance, liquidity/data
  freshness, strategy version, sports-specific risk policy, and operator
  `--enable-sports-paper` acknowledgment all pass. It supports the narrow
  pre-registered two-outcome, pre-game pilot only.

Every event has UTC timestamps, a `paper_run_id`, domain, asset/market, raw
quote/data references, policy/version hashes, status/rejection reason, and no
live order ID. Restart recovery reconciles persisted open paper positions with
fresh venue state/official settlement before new entries. In an unresolved or
ambiguous state, it stops entry, exposes reconciliation required, and never
invents a close.

### 6. Make paper safety an executable invariant

**Decision.** All entry points construct a `PaperExecutionGuard` before any
authenticated client or strategy cycle. It verifies `PAPER_TRADING=true`,
`KALSHI_USE_DEMO_ENV=true` for authenticated requests, an explicit paper-run
mode, safe database target, and zero live-order adapter instances. Production
order/amend/cancel and exit-trigger methods are not passed into paper-run
constructors. The guard logs a non-secret effective configuration fingerprint.

`EmergencyControl` is shared at the top level and applies a global halt plus
domain/asset/group budgets. A halt stops new entries immediately; existing
paper positions follow the domain's predeclared close/reconciliation rules.
Resumption requires a fresh operator invocation and records approver/time.

**Rationale.** A boolean alone is too easy to misuse, particularly when
read-only authenticated data and real-order clients share a vendor SDK.

### 7. Use staged gates rather than "start everything"

**Decision.** Implementation lands with modes `disabled`, `observe`,
`backtest`, `shadow`, and `paper`; `live` is unavailable to this change. The
default asset registry is BTC/ETH/SOL/XRP with every domain initially
`observe` or `backtest`. Promotion is one domain/asset at a time:

1. import/validate underlying data and Kalshi discovery snapshots;
2. pass frozen per-asset out-of-sample validation and execution assumptions;
3. run shadow mode (decisions but no paper fills) with data freshness and
   reconciliation checks;
4. pass a signed paper-admission report; then
5. run paper mode with a small, domain-specific paper bankroll/budget.

Sports adds a prerequisite: the completed feasibility report must have a
pre-registered `research_promising` verdict based on sufficient captured
observations. Perps require separate funding/mark/metadata coverage and
bracket/liquidation tests. Failing or insufficient evidence demotes to
`observe`/`backtest`; it never silently falls through to paper.

### 8. Build an operator-first control plane and website

**Decision.** The website has three first-class areas—Prediction Markets,
Perpetuals, and Sports—plus an all-domain overview. Each displays data
coverage, source/manifest, freshness, life-cycle state, candidate status,
validation/paper metrics, risk budget, current paper positions, and blockers.
Pages have read-only defaults; any future run control requires local
authentication, a typed paper-only confirmation, and an audit record. The
command line remains the authoritative way to initiate runs in this change.

## Risks / Trade-offs

- [Archive availability, rate limits, or geographic restrictions] → Pin
  downloaded artifacts, validate checksums, cache locally, and allow a
  source-adapter fallback; failure blocks affected assets rather than imputing.
- [A source revises historical data] → Preserve original raw files/hash and
  manifest; import a new version instead of mutating validated evidence.
- [USDT/USD, index, venue, or timestamp differences create false signals] →
  retain venue/quote currency, perform source-alignment checks, use
  source-specific features, and block unverified conversions.
- [Survivorship/liquidity bias in easy-to-download bars] → retain full coverage
  and gaps, feature only as-of data, model spread/volume/liquidity, and report
  unavailable intervals.
- [Paper fills look better than executable fills] → taker-first, side-aware
  pricing, observed liquidity caps, no invented maker fills, and compare paper
  execution quality to frozen assumptions.
- [Perp simulation understates liquidation/funding risk] → separate ledger,
  conservative margin/fee/funding treatment, price-gap stress tests, bracket
  tests, leverage ceiling, and an independent gate.
- [Sports information is late, proprietary, or conflictual] → timestamped
  allowlisted providers, availability cutoffs, conflict status, no entry on
  ambiguous evidence, and paper-only narrow scope.
- [One correlated crypto moves all strategies together] → asset, domain,
  major-crypto group, and portfolio budgets; one asset/domain promotion at a
  time.
- [Credentials or production endpoints are accidentally used] → compulsory
  `PaperExecutionGuard`, demo environment, dependency injection that excludes
  mutating clients, unit tests, and startup refusal.
- [Scope turns into an endless platform rebuild] → phase tasks have explicit
  acceptance tests and promotion gates; unresolved data/vendor questions block
  only the relevant adapter.

## Migration Plan

1. Inventory and retain the current DB, raw files, BRTI records, existing
   strategy reports, and paper trades. No destructive migration or replay is
   permitted.
2. Add additive schema migrations, raw-artifact storage, manifests, and
   source adapters. Import a small checksum-verified fixture first; test all
   parsers, idempotency, gap reports, and time semantics.
3. Narrow the shipped active registry to BTC/ETH/SOL/XRP, initially non-paper.
   Preserve historical rows for other assets but render them archived/non-active
   in the dashboard.
4. Implement external-data validation/backtests and compare BTC results to the
   legacy BRTI-only result without claiming equivalence. Freeze new baseline
   manifests and per-asset gates.
5. Introduce shadow orchestration and domain-specific paper ledgers; migrate
   the existing BTC binary loop through the new adapter only after output
   parity/restart tests pass. Keep its legacy command as a forwarding shim for
   one release with a deprecation warning.
6. Add perpetual paper mode and validate with fixtures, captured market data,
   funding, margin, and failure/recovery drills; no automatic hedge activation.
7. Complete sports feasibility evidence, then implement the limited sports
   adapter only if its precondition is met. Otherwise leave sports disabled and
   show the exact missing evidence.
8. Deploy in observe → backtest → shadow → paper order, one domain/asset at a
   time. Rollback means stop the foreground run, request an emergency halt,
   mark affected adapter/config version blocked, preserve all records, and
   return that asset/domain to `observe`; migrations remain additive.

## Open Questions

- Confirm which spot/perp data sources are legally/network accessible from the
  operator's location and whether a paid provider is acceptable if public
  archives have gaps.
- Confirm the Kalshi reference-index/settlement definition for every BTC, ETH,
  SOL, and XRP event series currently listed; do not assume the ticker naming
  matches the external venue price.
- Choose the first narrow strategy per domain after baseline reports: directional
  underlying signal, event-market price-dislocation, funding carry, or another
  candidate. No strategy is pre-approved by this architecture.
- Select a licensed sports odds/evidence provider and exact pre-game leagues
  only after coverage/cost/terms review; decide if any external provider data
  may be retained locally.
- Set explicit numerical data coverage, liquidity, paper bankroll, per-asset,
  correlation-group, and portfolio limits using the initial baseline reports.
- Decide whether notification/chat control is in this change or a follow-up;
  the dashboard/CLI audit and emergency halt are required regardless.
