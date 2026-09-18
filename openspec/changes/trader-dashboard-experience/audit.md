# P0 Capability and Dependency Audit

Tasks 1.1–1.4 of `trader-dashboard-experience`. This is a source-based audit of the
repository at branch `v2-perps-scalping-and-frontend`. No trading process was started,
no capture was run, and no rendered-browser study was performed. Every claim below
cites `file:line`. Where the source did not settle a question, it is marked
**OPEN** rather than asserted.

Companion document: [`reconciliation.md`](./reconciliation.md) (task 1.2).

**2026-09-14 correction pass:** OPEN-1, OPEN-2, OPEN-3, OPEN-5, and OPEN-6 (§5)
are now resolved with concrete decisions recorded in `design.md` §6a/§8a and
implemented as `tasks.md` 1a.1 (session authentication) and 1a.2 (runner
heartbeat), both moved into P0 ahead of the original section 2-4 work, plus
resolutions folded into task 2.1's scope for the schema/read-model items.
OPEN-4 (order-book depth coverage) remains deliberately deferred to task 6.4.
This audit's field-by-field findings below are unchanged — a capability that
was "unavailable — no source" when audited did not become available; a
decision now exists for how each gap will be closed and by which task.

---

## 0. Executive summary

Five findings dominate everything downstream. Tasks 2.x+ should not begin until
these are understood; as of the correction pass above, none of the five is any
longer an open question blocking task 2.1 — each has an implementation path.

1. **The dashboard's halt control is not connected to any halt enforcement.**
   `/control/kill` (`src/kalshi_bot/web/app.py:382-385`) mutates a process-local
   in-memory flag. A durable, enforced halt ledger exists
   (`src/kalshi_bot/risk/governance.py:93-152`, table `emergency_halt_records`)
   but **no web code imports it**, and no runner reads it. See §3.

2. **There are two unrelated halt systems.** `risk/emergency_control.py`
   (in-process guards, what the paper runner actually gates on) and
   `risk/governance.py` (durable cross-process ledger, reachable only from the
   operator CLI). They do not observe each other. See §3.2.

3. **`SimulatedTrade` has no run/account foreign key**
   (`src/kalshi_bot/storage/models.py:1172-1206`). The prediction ledger cannot
   be scoped to a `paper_run_id` today. `queries.py:1165-1170` documents this
   limitation in its own comment and returns a coarse all-paper figure. This
   blocks the account-isolation requirement in `trader-portfolio-review`. See §1.4.

4. **Unrealized P&L is unavailable in every domain.** No table stores a position
   mark with a timestamp that a read model can join. `PerpPositionView` carries
   `latest_mark` but no mark age (`queries.py:1007-1021`). See §1.2.

5. **Alerts, watchlists, journal notes and operator-action audit have no storage
   at all.** No table matches those concepts anywhere in `storage/models.py`.
   These are net-new additive migrations, not read models over existing data.

Regression baseline (task 1.4): **986 passed, 3 deselected, 0 failed.** See §4.

---

## 1. Capability matrix (task 1.1)

### 1.0 Conventions actually in use

Before the field tables, the three conventions the specs ask about, as actually
observed in the schema.

#### Money units

There is **no single convention**. Four distinct representations coexist:

| Representation | Where | Example |
|---|---|---|
| Integer cents | prediction contract prices | `SimulatedTrade.entry_price_cents`, `exit_price_cents` (`models.py:1194,1197`); `SignalRecord.market_yes_price` "# cents" (`models.py:1085`) |
| Float USD | all P&L and fee fields | `SimulatedTrade.gross_pnl_usd/entry_fee_usd/exit_fee_usd/fee_usd/net_pnl_usd` (`models.py:1202-1206`); `PerpPaperPosition.realized_pnl_usd/funding_pnl_usd/fee_usd` (`models.py:724-726`) |
| Decimal-as-string | captured public market data | `PublicTrade.price_dollars: String(32)` (`models.py:222`); `BRTIObservation.value_dollars: String(32)` (`models.py:239`) |
| Float, unit implied by domain | perp prices | `PerpPaperPosition.entry_price: Float` (`models.py:721`) — quote currency is **not** stored on the row |

Consequences for the read models:
- Nothing is currency-tagged. There is no `currency` column on any P&L or price
  column in `storage/models.py`. USD is implied by field name (`_usd`) only.
- `PerpPaperPosition` stores no quote currency, so the
  `trader-market-discovery` requirement that "perpetual quotes SHALL identify
  quoted currency" (`specs/trader-market-discovery/spec.md:11`) has **no source
  column**. It must be derived from the registry or declared unavailable.
- Decimal-as-string exists specifically to avoid float drift on captured data.
  Read models must not cast these to float and then re-round for display; the
  design's "canonical decimal/integer representation, round only for display"
  (`design.md:139`) is satisfiable for captured data and **not** satisfiable for
  perp P&L, which is already float in storage.

#### Capital / account identity

The actual key is **`paper_runs.id`** (`models.py:516`), a `String(64)`. There is
no `account` table and no `account_id` column anywhere in `storage/models.py`.

- A "run" carries `domain` (`prediction|perp|sports|ops`), `mode`, `asset_ids`
  (JSON), `status`, `config_fingerprint`, and since schema v14 `strategy_id`,
  `strategy_config_version`, `strategy_gate_status` (`models.py:516-537`).
- **Starting capital is not stored on the run.** It comes from
  `settings.bankroll_total_usd` at process start
  (`scripts/run_paper_trading.py:151`, `execution/paper_broker.py:67,73`). Two
  runs started with the same setting are indistinguishable in the DB by capital.
  This is exactly the "duplicate paper capital" case the portfolio spec calls out
  (`specs/trader-portfolio-review/spec.md:6-8`), and the DB offers no way to tell
  them apart — see the fixture in §4.2.
- The perp ledger **is** run-scoped: `PerpPaperPosition.paper_run_id` is a real FK
  (`models.py:715`). The prediction ledger **is not**: `SimulatedTrade` keys to
  `backtest_run_id` only (`models.py:1183`), which is null for paper rows.
- The synthetic per-day `ops` run is a command audit, not a trading run, and is
  filtered out at `queries.py:984`.

**Ownership decision needed:** the specs say "scoped by domain, venue, mode,
account and run" (`specs/trader-portfolio-review/spec.md:4`). Today only
`domain`, `mode` and `run` exist. `venue` and `account` have no columns. Marked
**OPEN-1** in §5.

#### Valuation / timestamp convention

The causal-provenance pattern is real and consistently applied **on captured
market data**, and absent on ledger rows.

| Convention | Meaning in this codebase | Where |
|---|---|---|
| `observed_at` | exchange/source event time | `OrderBookSnapshot.observed_at` (`models.py:200`), `PublicTrade` (`models.py:220`), `BRTIObservation` (`models.py:237`), `KalshiMarket.observed_at` (`models.py:125`) |
| `available_at` | when the bot could first have used it | `OrderBookSnapshot.available_at` (`models.py:201`), `PublicTrade` (`models.py:221`), `BRTIObservation` (`models.py:238`) |
| `fetched_at` | local wall-clock receipt | `models.py:204,226,243` etc. |
| `capture_session_id`, `source_endpoint`, `provenance` | capture lineage | same rows |

The design's rule "do not conflate ingest time and exchange observation time"
(`design.md:139`) is already enforced in capture tables. The explicit statement of
intent is in `PerpFundingEstimateObservation`'s docstring
(`models.py:750-758`): exchange `computed_time` → `observed_at`, local receipt →
`available_at`, "makes an estimate usable only after the bot could actually have
received it."

**The ledger tables do not follow this.** `PaperAuditEvent` has `observed_at`
only (`models.py:550`). `PerpPaperEvent` has `observed_at` only
(`models.py:735`). `SimulatedTrade` has `entry_ts`/`exit_ts`
(`models.py:1195,1198`). `PerpPaperPosition` has `entry_ts` (`models.py:722`).
None has `available_at`. So for any ledger-derived value the dashboard shows,
**the freshness/age can be computed but the availability semantics cannot** —
there is one timestamp, and it is the event's own time.

Two clocks are used for "now": `SignalRecord.created_at` is a timezone-aware
`DateTime` (`models.py:1071-1073`) while `evaluated_at_ts` is an integer epoch
"# market time" (`models.py:1075`). Read models joining signals must not mix them.

---

### 1.1 P&L fields

| Field | Exists? | Source | Units | Notes |
|---|---|---|---|---|
| Realized P&L — prediction | **Yes** | `simulated_trades.net_pnl_usd` (`models.py:1206`), read via `queries.py:1161-1177` | float USD | Only for `status in ('settled_won','settled_lost')` and `net_pnl_usd is not null` (`queries.py:1171-1175`). **Not run-scoped** — see §1.4. |
| Realized P&L — perp | **Yes** | `perp_paper_positions.realized_pnl_usd` (`models.py:724`) | float USD | Nullable while open. Run-scoped via `paper_run_id`. |
| Realized P&L — sports | **Unavailable — no source** | — | — | No sports ledger table exists. `sports_*` tables (`models.py:784-1014`) are capture/research only: discovery, candles, order books, trades, gaps, flow features, evidence cards, LLM reviews. No position or trade table. |
| Unrealized P&L — all domains | **Unavailable — no source** | closest: `PerpPositionView.latest_mark` (`queries.py:1017`) from the most recent `perp_paper_events` row with `event_type='mark'` (`queries.py:1096-1104`) | float, unit implied | There is **no stored unrealized field** in any domain. It would have to be computed as `(mark − entry) × signed_quantity × multiplier`. The mark's **timestamp is not returned** by `PerpPositionView`, so the spec's required "valuation basis and age" (`specs/trader-portfolio-review/spec.md:11`) cannot be satisfied without a query change. For prediction, `PaperBroker` computes an equity estimate in-process at `scripts/run_paper_trading.py:274` but never persists it. |
| Net P&L | **Partial** | perp: computed at `queries.py:1155-1158` as `realized + funding − fee`; prediction: `sum(net_pnl_usd)` at `queries.py:1176` | float USD | Perp net is a **realized-only** net; it excludes open positions because `realized_pnl_usd` is null while open. Labelling this "net P&L" on the desk without that qualifier would be wrong. |
| Fees | **Yes** | prediction: `entry_fee_usd`, `exit_fee_usd`, `fee_usd` (`models.py:1203-1205`); perp: `perp_paper_positions.fee_usd` (`models.py:726`) | float USD | Prediction fee decomposition is deliberate and documented (`models.py:1199-1202`): entry fee always charged, exit fee only on early close, `fee_usd` is their sum. Good enough for the "without double-counting" requirement. |
| Funding | **Yes (perp only)** | `perp_paper_positions.funding_pnl_usd` (`models.py:725`) | float USD | Counted exactly once in `queries.py:1155-1158`. Per-event funding also in `perp_paper_events.funding_rate` (`models.py:739`). |
| Cash / available capital | **Unavailable — no source** | closest: `settings.bankroll_total_usd` (config, not a record) | — | `PaperBroker._cash` (`execution/paper_broker.py:73`) is in-process; rebuilt on restart by replaying trades (`paper_broker.py:78-96`) and never written to a table. The desk's "Available capital" tile must render `Unavailable`, which is what `design.md:85` already requires ("Missing capital is `Unavailable`, never `$0`"). |
| Equity curve | **Partial — backtest only** | `queries.equity_curve` (`queries.py:443`), consumed at `app.py:170-172` | float USD | Derived from `SimulatedTrade` rows for **one `backtest_run_id`** plus `settings.bankroll_total_usd`. Not available for a paper run (no run key). |
| Return % / denominator | **Unavailable** | — | — | Requires a capital denominator per the spec (`specs/trader-portfolio-review/spec.md:11`); no per-run capital is recorded. Must be undefined until OPEN-1 resolves. |
| Win rate / profit factor / drawdown | **Derivable, prediction only** | from `simulated_trades.status` + `net_pnl_usd` | — | Resolved trades only, per spec. Same run-scoping caveat. `DrawdownGuard` computes drawdown in-process (`risk/drawdown_guard.py`) but persists nothing. |

### 1.2 Position fields

| Field | Exists? | Source | Units |
|---|---|---|---|
| Instrument / ticker | **Yes** | `perp_paper_positions.market_ticker` (`models.py:720`); `simulated_trades.market_ticker` (`models.py:1190`) | text |
| Domain | **Yes** | `paper_runs.domain` (`models.py:517`) | text |
| Venue | **Unavailable — no source** | — | No `venue` column on any position/run table. Single-venue (Kalshi) is implied throughout. |
| Side | **Yes** | prediction: `simulated_trades.side` `yes|no` (`models.py:1191`); perp: sign of `signed_quantity` (`models.py:721`), surfaced as `PerpPositionView.is_long` (`queries.py:1032-1034`) | — |
| Quantity | **Yes** | `simulated_trades.quantity: Float` (`models.py:1193`, deliberately float — see comment `models.py:1191-1193`); `perp_paper_positions.signed_quantity` (`models.py:721`) | contracts |
| Average entry | **Partial** | `simulated_trades.entry_price_cents` (`models.py:1194`); `perp_paper_positions.entry_price` (`models.py:721`) | cents / float | These are **per-trade entry prices, not averaged positions**. No table aggregates multiple fills into one average-entry position. If a domain ever produces two fills for one logical position, there is no averaging layer. |
| Latest mark | **Partial (perp only)** | `queries.py:1096-1104`, latest `perp_paper_events` `event_type='mark'` | float | **Mark age not exposed** — see §1.1. |
| Multiplier | **Yes (perp)** | `perp_paper_positions.multiplier` (`models.py:722`) | float | Not returned by `PerpPositionView` (`queries.py:1007-1021`) — needed for correct notional. |
| Margin | **Partial** | `perp_paper_events.margin_usd` (`models.py:740`) | float USD | Event-level only; not surfaced in `PerpPositionView`. |
| Leverage | **Unavailable — no stored field** | derivable from notional/margin | — | |
| Liquidation price / distance | **Yes (perp)** | `perp_paper_events.liquidation_price` (`models.py:741`), taken from the **first fill event** (`queries.py:1093`); distance computed `queries.py:1024-1030` | float | Note: liquidation is read from the opening fill and **not refreshed** as margin changes. Displaying it as current is a correctness risk. Flagged **OPEN-3**. |
| Stop loss / take profit | **Yes (perp)** | `perp_paper_events.payload['bracket']` JSON (`queries.py:1092`) | float | JSON blob, not a column. |
| Max loss / payout (prediction) | **Derivable** | contract accounting: max loss = `entry_price_cents/100 × quantity` | — | Not stored; computed in `run_paper_trading.py` for sizing only. |
| Strategy / run attribution | **Yes (perp)** / **No (prediction)** | `perp_paper_positions.paper_run_id` (`models.py:715`); `paper_runs.strategy_id` (`models.py:533`) | — | Prediction positions have no run link. |
| Settlement / funding horizon | **Partial** | `kalshi_markets.close_ts` (`models.py:121`); funding times not stored per-position | — | |

### 1.3 Quote fields

| Field | Exists? | Source | Units |
|---|---|---|---|
| Top-of-book bid/ask | **Yes** | `order_book_snapshots.bids` / `.asks` JSON (`models.py:202-203`) | JSON; prediction cents |
| Depth ladder | **Partial — depends on capture** | same JSON columns | — | The columns are `JSON` and can hold a ladder, but whether depth beyond top-of-book was actually captured is a **data question, not a schema question**. The spec's "Depth unavailable" path (`specs/trader-market-discovery/spec.md:13-15`) must be driven by inspecting the stored JSON per row, not by a schema flag. Flagged **OPEN-4**. |
| YES/NO sides | **Partial** | `SignalRecord.market_yes_price` is YES cents (`models.py:1085`); `simulated_trades.side` (`models.py:1191`) | cents | NO price is **not stored**; deriving it as `100 − yes` must be labelled derived, per `specs/trader-market-discovery/spec.md:11`. |
| Perp mark / quote currency | **Partial** | `perp_mark_observations` (`models.py:246-288`) | — | Quote currency not a column — see §1.0. |
| Spread | **Derivable** | from bid/ask | — | Not stored. |
| Volume / open interest | **Unavailable on Kalshi markets** | closest: `public_trades` row counts (`models.py:209-228`), `sports_public_trades` (`models.py:903`) | — | `kalshi_markets` (`models.py:99-130`) has **no volume or open-interest column**. The markets list cannot sort by volume without deriving it from trade counts. |
| Quote age / freshness | **Yes** | `observed_at`/`available_at` on all capture tables; `FeedHealth.age_s` + `.status` (`queries.py:670-688`) | seconds | `FeedHealth.status` returns `live|late|stale|empty` using per-feed `expected_interval_s` (`queries.py:678-688`) — this **already implements** the spec's source-specific cadence rule (`specs/trader-workspace/spec.md:32`). Reuse it; do not reinvent. |
| Fee-adjusted edge | **Yes** | `signals.fee_adjusted_edge` (`models.py:1090`) | float | Nullable. Null must render "unavailable", never 0 — `specs/trader-market-discovery/spec.md:6-8`. |
| Contract rules / settlement criteria | **Partial** | `kalshi_markets.strike_type/floor_strike/cap_strike` (`models.py:113-117`); sports: `sports_market_rule_provenance` (`models.py:801-818`) | — | Crypto markets have strike structure but **no rules source link or version**. Sports has a dedicated provenance table. Asymmetric coverage. |

### 1.4 Order / fill lifecycle fields

**This is the weakest area in the audit.**

| Field | Exists? | Source |
|---|---|---|
| Order lifecycle (pending→filled/cancelled) | **Unavailable — not persisted to DB** | `execution/order_tracker.py:38-40` — `OrderTracker` is a "persistent idempotency registry" that writes **a JSON file** (`order_tracker.py:41-55`), not a table. Critically, **it has zero call sites**: a repo-wide grep for `OrderTracker(` outside its own module returns nothing. It is dead code today. |
| Partial fills | **Partial** | `TrackedOrder.filled_quantity` / `.remaining_quantity` (`order_tracker.py:22,34-36`) exist in the dataclass but, per the above, are never populated in any running path. In the DB: **no partial-fill representation exists** — `SimulatedTrade` is one row per closed position with a single `quantity`. |
| Fills | **Partial** | perp: `perp_paper_events` rows with `event_type='fill'` (`models.py:733`); prediction: `simulated_trades` rows; counts via `RunHealthReport` ledgers (`queries.py:967`) |
| Reject reasons | **Yes (as audit events)** | `paper_audit_events.reason` (`models.py:552`); `PaperBroker.place_order` returns a rejection with reason (`paper_broker.py:152`) |
| Order IDs | **Unavailable in DB** | `TrackedOrder.client_order_id` / `.broker_order_id` (`order_tracker.py:19-20`) — JSON file only |

**Conclusion for `trader-portfolio-review`:** the spec's "Fill without order lifecycle"
scenario (`specs/trader-portfolio-review/spec.md:20-22`) is not an edge case here —
it is the **default state for every domain**. The UI should state "Order lifecycle
not recorded" broadly, and the order-history view (task 7.3) must be built on fills,
not orders.

### 1.5 Risk limits and usage

| Field | Exists? | Source |
|---|---|---|
| Daily loss limit | **Yes (config)** | `settings.max_daily_loss_usd`, enforced by `DailyLossGuard` (`risk/daily_loss_guard.py`), composed at `run_paper_trading.py:145` |
| Drawdown pause/halt pct | **Yes (config)** | `settings.max_drawdown_pause_pct` / `max_drawdown_halt_pct` (`run_paper_trading.py:141-142`) |
| Consecutive losses | **Yes (config)** | `settings.max_consecutive_losses` (`run_paper_trading.py:147`) |
| Per-position size | **Yes (config)** | `FixedRiskConfig(risk_pct, max_position_pct)` (`app.py:128`, `run_paper_trading.py:157-159`) |
| **Current usage against any limit** | **Unavailable — no source** | Every guard holds its counters **in process memory** and persists nothing. `EmergencyControl.snapshot()` returns a `HaltState` (`risk/emergency_control.py:100-107`) that exists only inside the runner process. The dashboard is a different process (§3.1) and cannot read it. |
| Blocks-new-entries flag | **Yes (per run, derived)** | `PaperRunSummary.blocks_new_entries` (`queries.py:914`) from `build_run_health_report` — this is **reconciliation-derived**, not guard-derived |
| Blocked-fill reasons | **Yes** | `PaperRunSummary.blocked_fill_reasons` (`queries.py:915-919`), from the `preflight_passed` audit event payload (`queries.py:941-956`) |

**Conclusion:** the risk page (task 7.4) can show **policy** (from config) and
**reconciliation/admission blockers** (from the DB), but **cannot show live guard
usage** — no daily-loss-so-far, no current drawdown. Those must render as
unavailable-with-reason until a guard state is persisted. Flagged **OPEN-2**.

### 1.6 Alert, journal, watchlist, preference, operator-action fields

| Concept | Exists? | Source |
|---|---|---|
| Alerts (severity, first/last seen, occurrence count, ack, resolve) | **Unavailable — no source.** No table matches; a case-insensitive grep for `alert` in `storage/models.py` returns nothing. | Entirely new (tasks 2.3, 8.5) |
| Journal notes / tags | **Unavailable — no source.** No `journal`/`note` table. | Entirely new (task 2.4) |
| Watchlists | **Unavailable — no source.** | Entirely new (task 2.2) |
| Operator-action audit (request ID, before/requested/observed state) | **Partial.** `paper_audit_events` (`models.py:539-558`) is append-only and carries `kind`/`status`/`reason`/`payload`, and the `ops` synthetic run records CLI commands (`queries.py:981-983`). But it is keyed to a `paper_run_id` FK (`models.py:546`) — **a dashboard action with no run has nowhere to go**. `emergency_halt_records` (`models.py:1208-1235`) is the closest true audit row and carries `source`, `reason`, `created_at`, `operator`, `policy_snapshot`, `health_snapshot`. | Extend, don't reinvent (task 2.3) |
| Display preferences | **Yes** | `dashboard_settings` key/value JSON (`models.py:1268-1283`), read/written by `web/theme.py` (`load_theme`/`save_theme`, used `app.py:389,415,424,430`). Design's "preserve existing themes" (`design.md:61`) is satisfiable: `PRESETS` and `ThemeColors` at `web/theme.py`. |

Migrations are additive and SQLite-native with a `PRAGMA user_version` gate
(`storage/migrations.py:70-165`), currently `SCHEMA_VERSION = 16`
(`migrations.py:7`). The design's "additive storage migrations only"
(`design.md:151`) matches the existing mechanism exactly.

### 1.7 Freshness / availability metadata

The design requires every read model to carry scope, stable row ID, source
timestamp, fetch timestamp, freshness and availability
(`design.md:139`). Today:

- **Freshness: partially available.** `FeedHealth` (`queries.py:656-688`) is a
  working per-feed implementation with source-specific cadence. Nothing else
  carries freshness.
- **Availability: not represented.** No read-model dataclass in `queries.py` has
  an `availability`/`reason` field. Several encode availability implicitly as
  `None` (e.g. `PerpPositionView.latest_mark`, `LabAccountComparison.net_pnl_usd`)
  — which is exactly the ambiguity the spec forbids, because `None` currently
  cannot be distinguished from "zero" at the template layer.
- **Stable row IDs: mostly available.** `paper_runs.id`, `perp_paper_positions.id`,
  `simulated_trades.id`, `signals.id` are all real PKs. `PaperRunSummary`
  exposes `run_id` (`queries.py:903`); `PerpPositionView` **does not expose the
  position `id`** (`queries.py:1007-1021`) — a drilldown route has no key. Needs
  a query change in task 7.2.

---

## 2. Change reconciliation (task 1.2)

Full detail in [`reconciliation.md`](./reconciliation.md).

**`openspec/specs/` confirmation:** verified **empty** — `ls -la openspec/specs/`
returns only `.` and `..`, and `find openspec/specs -type f` returns nothing.
The proposal's claim at `proposal.md:27` is **correct and still true**. There are
zero living capability files, so no MODIFIED-requirement work is possible in this
change; all four specs correctly use `## ADDED Requirements`.

---

## 3. Control-path trace (task 1.3)

### 3.1 The process boundary (the root cause)

The dashboard and the paper runner are **separate OS processes**:

- The dashboard is `uvicorn.run(create_app(), ...)` in
  `scripts/start_dashboard.py:54`.
- Paper start spawns a **child process**: `subprocess.Popen(("uv","run","python",
  "scripts/run_paper_trading.py"), ...)` at `web/operations.py:113-118`.

`ControlPanel` is a module-level singleton returned by `get_control_panel()`
(`web/control_state.py:52-56`). Each process imports the module separately and
therefore gets **its own instance**. The docstring is explicit that it is
"Process-local and in-memory on purpose" (`control_state.py:7-8`).

This single fact determines every row in the table below.

### 3.2 The two halt systems

| | `risk/emergency_control.py` | `risk/governance.py` |
|---|---|---|
| State | in-process guard objects | `emergency_halt_records` table (`models.py:1208`) |
| Durable across restart? | **No** | **Yes** — "A new process start reads the latest row and never clears a halt on its own" (`models.py:1215-1216`) |
| Cross-process? | **No** | **Yes** — "it reads the latest persisted row on every call so a second process observes the same state" (`governance.py:95-97`) |
| Enforced by the paper runner? | **Yes** — `control.allows_new_entries(now_dt)` at `run_paper_trading.py:276`, suppressing entries at `:321-328` | **No** — no runner imports it |
| Reachable from the dashboard? | **No** (different process) | **No** — grep confirms `web/` never imports `governance` |
| Reachable from the CLI? | No | **Yes** — `operator_cli.py:179-199` (`_cmd_halt`, `_cmd_resume`) |

The durable, correct halt machinery the design assumes ("Wire through existing
emergency/governance machinery", `design.md:131`) **exists and is well built** —
it is simply not connected to the web tier at either end.

### 3.3 Control-by-control

| Control | Route / function | Real or intent-only? | Target scope actually reached |
|---|---|---|---|
| **Paper start** | `POST /operations/paper/start` → `app.py:340-345` → `PaperProcess.start()` (`operations.py:110-118`) | **Real** — spawns an actual OS subprocess | Exactly one unnamed `run_paper_trading.py` child of this dashboard process. **Not** the multi-venue orchestrator (`scripts/run_paper.py`), **not** the strategy-lab launcher. No account/run/config selection: the command is hardcoded with no arguments (`operations.py:114`). Guarded by `settings.paper_trading` (`app.py:342-343`). Duplicate-start protection exists but is **only in-process** (`operations.py:111-112`) — it checks a handle this process owns, so it cannot detect a runner started by the CLI or a previous dashboard. |
| **Entry halt** | `POST /control/kill` → `app.py:382-385` → `ControlPanel.kill()` (`control_state.py:43-49`) | **INTENT-ONLY.** Sets `halted=True` on the dashboard's own in-memory object. | **Nothing.** No process reads this instance. The spawned runner calls `get_control_panel()` in its own process (`run_paper_trading.py:136`) and gets a different object. The button changes a banner (`templates/_control_status.html:6`) and nothing else. |
| **Resume / arm** | `POST /control/arm` → `app.py:375-380` → `ControlPanel.arm()` (`control_state.py:35-41`) | **INTENT-ONLY**, same reason. | Nothing. Note the runner **self-arms** at startup regardless: `panel.arm()  # this loop running IS the operator's intent` (`run_paper_trading.py:136-137`). |
| **Process stop** | `POST /operations/paper/stop` → `app.py:347-350` → `PaperProcess.stop()` (`operations.py:120-122`) | **Real, but narrow** — `self.process.terminate()` | Only a child this dashboard process spawned and still holds a handle to. **After a dashboard restart the handle is `None` and Stop silently does nothing** — `stop()` has no else branch (`operations.py:120-122`) and the route always returns 303 (`app.py:349`). An externally started runner is unreachable and invisible. |
| **Emergency acknowledgement** | — | **Does not exist.** | No route, no per-target acknowledgement, no request ID. `emergency_halt_records` can record a halt with source/reason/operator/policy snapshot (`models.py:1222-1234`) but no web code writes it. |
| **Capture start/stop** | `POST /operations/capture/{start,stop}` → `app.py:352-360` → `CaptureProcess` (`operations.py:129-139`) | **Real** — `cmd /c start_capture.bat` | Same handle-loss caveat as paper stop. |
| **Allowlisted jobs** | `POST /operations/{name}` → `app.py:362-370` → `OperationManager.start` (`operations.py:71-80`) | **Real** | Strictly allowlisted via the `COMMANDS` dict (`operations.py:12-50`); unknown names 404 (`app.py:366-367`). This already satisfies "no arbitrary shell command" (`specs/trader-operations-workflow/spec.md:39`). Note `openspec_validate` is hardcoded to validate `multi-venue-paper-trading` (`operations.py:15`). |

### 3.4 One subtlety worth recording

`EmergencyControl` **does** read the panel:
`allows_new_entries()` returns `False` if `self._control_panel.snapshot().halted`
(`emergency_control.py:91-94`), and `_trip()` calls `control_panel.kill()`
(`emergency_control.py:80-87`). `run_paper_trading.py:150` passes
`control_panel=panel`.

So the wiring pattern is genuinely correct **within one process**. The design
comment at `emergency_control.py:20-23` — "an operator watching the dashboard sees
the SAME halt state a live loop is enforcing" — describes a true property of a
single-process deployment and a **false** one of the actual two-process
deployment the dashboard creates via `Popen`. This is the precise gap task 4.2
must close, and the fix is to move the shared state to `emergency_halt_records`
via `GlobalEmergencyControl`, which already has the right semantics.

### 3.5 Mutation safety

- **POST/redirect/GET: yes** — every mutation returns `RedirectResponse(..., 303)`.
- **CSRF / same-origin: none.** No middleware, no token, no `Depends` in
  `app.py` (grep for `csrf|auth|Depends|middleware` returns nothing).
- **Idempotency / deduplication: none.** No request IDs on any route.
- **Audit records: none** for web actions.
- **Auth: none.** `dashboard_auth_secret` (`config/settings.py:264`) defaults to
  `None` and is checked **only** as a bind-address guard in
  `start_dashboard.py:40-47`. It does not authenticate any request. The
  proposal's own warning (`proposal.md` risks, `design.md:182`) is accurate.

Tasks 4.4's requirements (CSRF, dedup, outcome lookup) are all **net-new**.

### 3.6 Unresolved / unsupported paths — stated plainly

1. Halt cannot reach any runner. **Unsupported today.**
2. Resume has no revalidation path from the web at all.
3. No per-target acknowledgement exists, so the spec's partial-acknowledgement
   scenario (`specs/trader-operations-workflow/spec.md:20-22`) has nothing to
   report against. It must render "unknown" for every target until 4.2 lands.
4. Externally started runners (CLI, previous dashboard) are **invisible** to the
   dashboard and unreachable by its controls — directly contradicting
   "show observed existing external processes" (`design.md:129`). There is no
   PID file, heartbeat table, or process registry. Flagged **OPEN-5**.
5. Sports and perp runners have **no start control at all** in the web tier; only
   the hardcoded BTC `run_paper_trading.py` is launchable.

---

## 4. Fixtures and regression baseline (task 1.4)

### 4.1 Regression baseline — recorded, not fixed

Run on this branch before any change by this task group.

| Suite | Command | Result |
|---|---|---|
| Dashboard/web + control-related | `uv run pytest tests/unit/test_dashboard_*.py tests/unit/test_asset_admissions.py tests/unit/test_brti_reconstruction_coverage.py tests/unit/test_paper_readiness.py tests/unit/test_emergency_control.py tests/unit/test_risk_governance.py tests/unit/test_operator_cli.py -q` | **99 passed**, 1 warning, 9.17s |
| Full suite | `uv run pytest -q` | **986 passed, 3 deselected**, 1 warning, 35.55s |

**Baseline: zero failures.** This change must not regress below 986 passing /
0 failing. There are no pre-existing failures to excuse a later red test.

**After this task group** (fixtures + their self-tests added, no production code
touched): `uv run pytest -q` → **999 passed, 3 deselected, 0 failed** — the 986
baseline plus the 13 new fixture self-tests, with no existing test disturbed.
`uv run ruff check` passes on all three new/modified test files.

Only warning: a `StarletteDeprecationWarning` from `fastapi/testclient.py`
(httpx vs httpx2) — third-party, unrelated, pre-existing.

Existing dashboard test files (the regression surface this change must preserve):
`tests/unit/test_dashboard_capture_panels.py`, `test_dashboard_operations.py`,
`test_dashboard_paper_runs.py`, `test_dashboard_strategy_lab.py`,
`test_dashboard_validation_panel.py`.

### 4.2 Fixtures added

New file: `tests/unit/conftest_dashboard_states.py`. The fixture names are
re-exported from `tests/unit/conftest.py`, which makes them available to any
test under `tests/unit/` without an import.

(Implementation note: `pytest_plugins` was the first approach and pytest
**rejects it outside a top-level conftest** — it fails collection for the whole
`tests/unit` directory. Re-exporting the names achieves the same registration
without adding a root-level conftest for this change alone. Recorded so task
10.1 does not rediscover it.)

Conventions match the existing dashboard tests exactly: in-memory
`create_engine("sqlite://")` + `Base.metadata.create_all`, per-test isolation,
no touching of the operator's real database.

| Fixture | Covers | Spec scenario it serves |
|---|---|---|
| `dashboard_session` | isolated in-memory DB | all |
| `empty_state` | no runs, no balances | `trader-workspace` "First launch without records" (`spec.md:13-15`) |
| `fresh_state` | run + recent feed observations within cadence | freshness `live` |
| `stale_state` | observations far older than `expected_interval_s` | `trader-workspace` refresh/staleness (`spec.md:32`) |
| `partial_state` | open position with **no mark event** | `trader-portfolio-review` "Missing position mark" (`spec.md:13-15`) |
| `error_state` | audit event with a failure status/reason | error surfaces |
| `duplicate_paper_capital` | **two runs, identical starting capital**, disjoint ledgers | `trader-portfolio-review` "Compare duplicate paper capital" (`spec.md:6-8`) |
| `partial_fill_state` | fill quantity < requested quantity | `trader-portfolio-review` order lifecycle (`spec.md:20-22`) |
| `disconnected_runner_state` | run `status='running'` with a stale last audit event (and the inverse) | `trader-operations-workflow` "Intent armed without process" (`spec.md:6-8`) |

New test file `tests/unit/test_dashboard_state_fixtures.py` asserts each fixture
actually produces the state it claims — a fixture that silently stops representing
its scenario is worse than no fixture.

**Scope note:** these are fixtures and their self-tests only. No dashboard
template, route, or read-model production code was modified in this pass, per the
P0 gate.

---

## 5. Open questions — decisions that belong to the user

These are recorded rather than decided unilaterally.

- **OPEN-1 — account identity. RESOLVED 2026-09-14.** The specs require scoping
  by "account" and "venue"; the DB has neither column, and per-run starting
  capital is not recorded (§1.0). Option (b) selected: add `account_id` +
  `starting_capital_usd` to `paper_runs`, plus a `paper_run_id` FK on
  `simulated_trades` so prediction-ledger rows can be attributed to a run. This
  is required for duplicate-capital comparison to be honest. It changes a table
  `multi-venue-paper-trading` owns (`reconciliation.md` §OWN-2) — implement
  under task 2.1, coordinated with that change's sign-off rather than landed
  unilaterally. See `design.md` §8a.

- **OPEN-2 — guard usage is unobservable across processes. RESOLVED 2026-09-14.**
  Daily-loss-so-far and current drawdown live only in runner memory (§1.5).
  Resolved: persist guard-usage snapshots (new table or a new
  `paper_audit_events` kind, per `design.md` §8a) written by each guard on
  evaluation; the risk page (7.4) and desk tile (5.1) read the latest snapshot
  per guard per run and show "usage unavailable" absent a recent one. Implement
  under task 2.1.

- **OPEN-3 — stale liquidation price. RESOLVED 2026-09-14.**
  `PerpPositionView.liquidation_price` comes from the **opening fill event**
  (`queries.py:1093`) and is not recomputed. Resolved: expose the fill event's
  `observed_at` as `liquidation_price_as_of` and label the value "Liquidation
  estimate (as of open, not recalculated)" until a recalculation path exists —
  a read-model/presentation change, no new persistence needed. See `design.md`
  §8a. Implement under task 2.1/7.2.

- **OPEN-4 — depth coverage is a data question. Deliberately deferred, not
  resolved in this pass.** Whether `order_book_snapshots` actually contains
  ladders or only top-of-book cannot be answered from the schema (§1.3). Must
  be measured against the operator's real DB before the market-detail depth
  view (task 6.4) is designed — correctly scoped there, not to task 2.1, since
  the snapshot/status read models do not depend on depth data.

- **OPEN-5 — external runner observability. RESOLVED 2026-09-14.** There is no
  PID file, heartbeat table, or registry (§3.6). Resolved: add a durable
  `runner_heartbeats` record (task 1a.2, P0, ahead of 2.1/3.2) written by each
  runner/capture process on its own existing loop cadence and by the
  dashboard's process handles where live, so the dashboard can honour
  `design.md:129` ("show observed existing external processes rather than
  falsely reporting all trading stopped") and task 2.1's "separate
  intent/process/entry-permission states" has real liveness evidence to build
  on. See `design.md` §8a.

- **OPEN-6 — halt authentication conflict. RESOLVED 2026-09-14 (user decision).**
  `multi-venue-paper-trading` requires a website halt to **fail closed when
  dashboard authentication is absent** (`specs/paper-trading-operations/spec.md:47-55`),
  while this change requires a halt control on **every view**
  (`specs/trader-operations-workflow/spec.md:18`). With `dashboard_auth_secret`
  defaulting to `None` (`config/settings.py:264`) and no request authentication
  anywhere (§3.5), a literal reading of multi-venue meant the halt button had to
  **not be exposed at all**. Resolved by building real whole-dashboard session
  authentication (`design.md` §6a) rather than treating loopback binding as the
  boundary or shipping the halt as visible-but-unavailable — see
  `reconciliation.md` §CONFLICT-1 for the full resolution and `tasks.md` task
  1a.1, sequenced in P0 ahead of task 4.2 which depends on it.

---

## 6. Sources

Read in full or in relevant part: `openspec/changes/trader-dashboard-experience/`
(proposal, design, tasks, four specs); the six reconciled changes' proposals and
overlapping spec files; `src/kalshi_bot/web/{app,queries,control_state,operations,
theme,export}.py`; `src/kalshi_bot/web/templates/`;
`src/kalshi_bot/storage/{models,migrations}.py`;
`src/kalshi_bot/risk/{governance,emergency_control}.py`;
`src/kalshi_bot/execution/{paper_broker,order_tracker,perp_paper,operator_cli}.py`;
`scripts/{run_paper_trading,start_dashboard}.py`; `tests/unit/` dashboard tests
and `conftest.py`.
