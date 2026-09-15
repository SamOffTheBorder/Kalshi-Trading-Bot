## Context

This is the detailed product and implementation plan for the local site launched by `start_dashboard.bat` / `scripts/start_dashboard.py`. Inspection covered the FastAPI routes, Jinja templates, CSS, refresh client, query functions, process controls, and related OpenSpec changes. This is a source-based audit; no running trading process was started and no rendered-browser usability study was performed.

### Existing strengths and gaps

| Area | Evidence in repository | Design response |
|---|---|---|
| Launch | Local FastAPI, Jinja, one batch launch, local CSS/JS | Preserve no-build startup and offline asset loading |
| Navigation | Nine links in `_base.html`; council accessible by route but absent from primary navigation | Group by trader task, with secondary views and deep links |
| Overview | Control, readiness, feed tables, evidence, backtests, sizing, decisions, placeholders | Show current session first; move research and operations detail to dedicated pages |
| Controls | `/control/arm` and `/control/kill` update in-memory intent; paper start/stop are separate POST routes | Present capability and authoritative process/guard acknowledgement separately |
| Copy | Overview says no paper broker/loop exists while Operations manages paper processes | Generate explanatory copy from actual capabilities and states |
| Data | Queries expose paper runs, perp positions, lab comparisons, admission, feeds and validation | Build typed read models over these sources; audit coverage before filling new fields |
| Refresh | `live.js` polls fragments every 10 seconds and silently ignores errors | Timestamp snapshots, show stale/disconnected states, prevent overlapping requests |
| Appearance | Existing dark palette and saved theme customization | Evolve tokens and density rather than discard preferences |

Stakeholder: a single local operator researching and monitoring automated paper/shadow strategies across Kalshi prediction markets, sports, and perpetuals. The primary landing context is Kalshi; venue/domain labels keep other instruments understandable.

## Goals / Non-Goals

**Goals:** Understand actual mode/state/risk within five seconds; find a blocker or a position in two navigation actions; follow a decision through signal, gate, fill, and outcome; conduct pre-session checks and post-session review without hunting through reports. Deliver readable laptop and mobile monitoring, honest data coverage, and reliable controls.

**Non-Goals:** New profitable strategies, advice on which asset to buy, live execution enablement, manual order submission, fund transfers, hosted multi-user SaaS, new market-data subscriptions, or a drag-and-drop terminal framework. Existing APIs and ledgers determine availability. Manual live tickets, cancel-all, and flatten-all require a later execution proposal with reconciliation and venue-specific semantics.

## Decisions

### 1. Information architecture and navigation

Use a 216px collapsible left navigation and a persistent 56px context bar. Six primary destinations reduce competition between domain and workflow links. Keep current URLs reachable, with aliases or redirects preserving query parameters and anchors.

| Primary destination | Contents / secondary navigation | Route plan |
|---|---|---|
| Trading Desk | Session summary, attention, positions, watchlist, recent decisions | `/` |
| Markets | All markets; Kalshi prediction, Sports, Perpetuals; saved watchlists; instrument detail | `/markets`, retain `/sports`, `/perps`, `/prediction-markets`; add `/markets/{domain}/{instrument_id}` |
| Portfolio | Positions, orders/fills, risk, performance, journal | `/portfolio` with tab/query state; `/portfolio/positions/{id}` |
| Strategies | Lab, validation/backtests, run detail, decision/council evidence | retain `/strategy-lab`, `/runs`, `/council`; add stable run/decision detail routes |
| Operations | Health, capture, jobs, alerts, action history | `/operations`, retain `/data`; add `/alerts` |
| Settings | Appearance, display/timezone, notifications, connection status, read-only policy | `/settings` |

Header: brand, selected account/run scope, venue/domain, persistent PAPER / SHADOW / BACKTEST / LIVE badge, observed engine status, snapshot age, alerts count, and `Halt new entries` when supported. Default to the latest paper context; remember selection, but validate it exists. A data-scope selector never changes execution mode. Live views display `Execution unavailable` until an independently implemented live adapter exists. Global account context follows links; page-specific filters remain in URLs. Provide breadcrumbs on detail pages.

Alternative considered: retain the flat topbar and only restyle cards. Rejected because it leaves workflow duplication and poor narrow-screen behavior. A command palette is unnecessary for initial delivery; keyboard-accessible search and navigation cover core use.

### 2. Visual direction and component system

Aim for a calm, dense trading workstation: charcoal canvas, crisp typography, aligned numbers, restrained color, and generous separation between sections. No decorative hero art, glowing status dots, or flashing prices.

| Token / component | Proposed default |
|---|---|
| Canvas / card / raised surface | `#0D1117` / `#151B23` / `#1D2633` |
| Main / secondary text | `#E6EDF3` / `#A8B3C2` |
| Action / positive / caution / danger | `#70A5FF` / `#45D6A0` / `#F1C66D` / `#FF7B86` |
| Borders / corners | 1px quiet border; 8px cards; 6px inputs/buttons |
| Type | Local system sans, 14px body, 12px metadata minimum, 20–24px page title; tabular numerals, monospace IDs only |
| Spacing | 4px base: 8/12/16/24/32px; 16px panel padding; 16px grid gap |
| Density | Comfortable 44px rows and compact 32px rows; essential touch actions at least 44px |
| Buttons | One primary action per panel; neutral secondary; danger reserved for halting/destructive actions |
| Status | Icon + explicit word + timestamp; positive P&L and a healthy process are separate concepts |

These colors are design candidates: measure contrast before acceptance. Normal text target >=4.5:1, large text and meaningful controls >=3:1. Custom palettes must warn on failing combinations and offer reset. Preserve existing presets through token mapping; add light mode, system preference, and density. Use signs as well as colors for P&L. YES/NO sides are textual labels with distinct neutral accents; neither means profitable/unprofitable.

Components: context selector, status badge, metric tile with basis/help text, alert row, sortable data table, tabs, filter bar, accessible detail drawer with full-page equivalent, labeled chart with table fallback, progress/gate checklist, empty-state panel, inline error/retry, confirmation dialog, and non-blocking toast. Avoid modal nesting. Pending requests disable only the relevant action; retain keyboard focus and scroll across refreshes. Respect reduced motion. No automatic sound; optional local sound only after opt-in.

### 3. Trading Desk layout

At 1440x900, essential state and attention must be above the fold; constrain lower lists to five rows with `View all`.

```text
+------------------+---------------------------------------------------------+
| Kalshi Bot       | Account / domain | PAPER | Engine state | age | Halt     |
|                  +---------------------------------------------------------+
| Trading Desk     | Trading Desk                  Session / timezone        |
| Markets          | [Net P&L] [Open risk] [Available capital] [Active runs] |
| Portfolio        +-----------------------------------+---------------------+
| Strategies       | Open positions (5)                | Needs attention (3) |
| Operations       | market, side, qty, mark, P&L, age  | reason + next step  |
| Settings         +-----------------------------------+---------------------+
|                  | Watchlist / opportunities (5)     | Engine / feed health|
|                  +-----------------------------------+---------------------+
|                  | Recent decisions: action, net edge, reason, evidence   |
+------------------+---------------------------------------------------------+
```

Summary tiles use the same scoped snapshot: session net P&L, open worst-case loss or domain-specific risk, available capital if recorded, and active runs. Each tile displays scope, time window, and incomplete coverage when applicable. Missing capital is `Unavailable`, never `$0`. Clicking a metric opens its filtered detail.

Attention sorts unresolved critical items first: halt not acknowledged, reconciliation mismatch, stale required data, risk guard, then validation/admission blockers. Every item names affected account/domain, first/last observed time, reason, and next action. Healthy accounts show a compact confirmation rather than an empty warning shell.

New installation: replace empty metric grids with a concise setup journey: check configuration -> start capture -> inspect freshness/coverage -> validate strategy -> start eligible paper run -> review decisions. Existing experienced users see their current session immediately. Starting capture and starting trading remain separate actions.

### 4. Markets and instrument detail

Markets defaults to a searchable list, not the instrument-admission report. Filters: domain/venue, event/category, asset, status, closing window, minimum observed liquidity, strategy admission, and freshness. Sort by closing time, spread, volume, or fee-adjusted edge when that field exists. Show active filters, result count, reset, stable pagination, column chooser, and watchlist star. Never present missing edge as zero or rank it as actionable.

Prediction/sports columns: event title + ticker, YES bid/ask in cents per contract, NO bid/ask when supplied or explicitly labeled derived, spread, available size, volume/open interest when available, close/settlement timestamps, signal/gate, freshness. Perpetual columns substitute quoted currency price, spread/bps, funding, asset and venue; do not reuse cents labels. Distinguish event group from tradable contract and group related outcomes.

Market detail: title, venue, lifecycle status, close countdown, separate expected settlement time, source/as-of; price history above liquidity and rules; side panel with watchlist and latest strategy assessment. Tabs: Overview, Quotes/depth, Decisions, Related positions, Contract rules. Charts distinguish observed bid/ask/mid and fair value, with explicit axes and sampling interval. Never draw a synthetic order book when only top-of-book is stored; show `Depth unavailable`. Gaps remain visible. Rules display recorded source link, version/as-of, settlement criteria, and resolver; missing metadata is identified and an official source link offered when known.

Signal detail displays model probability/fair value, executable-side price, fees, estimated slippage if available, fee-adjusted edge with units, size constraints, data age, decision time, and HOLD/blocker reason. Confidence is not labeled as win probability unless the originating model defines it that way. A planning-only payoff view may use existing sizing output; label all estimates and omit any submit button.

### 5. Portfolio, risk, orders, and review

Keep paper accounts and runs isolated by default. Cross-account comparison is a table, not a summed equity line across duplicate experimental capital. Aggregation is allowed only for explicitly compatible, disjoint ledgers, same currency/mode, same valuation time and window; disclose included accounts. Never mix backtest and paper outcomes.

Positions: instrument, domain/venue, side, quantity, average entry, latest mark/basis/age, realized/unrealized/net P&L, fees, risk, strategy/run, settlement/funding horizon. Perps add margin/leverage, funding paid/accrued, liquidation estimate and distance only where recorded and defined. Prediction positions show maximum loss/payout from existing contract accounting. No leverage-style risk applied to binary contracts. Detail joins position -> fills/orders -> originating decision -> strategy evidence.

Orders/fills: scoped status tabs and filters for instrument, time, strategy, order ID, side, reject reason. Display partial fills, quantities, fee/slippage and lifecycle timestamps. Rejected/canceled/unfilled decisions must not count as fills. If a domain records fills without orders, show fills and `Order lifecycle not recorded`, preserving evidence rather than constructing fictitious orders.

Risk: current policy beside current usage: daily loss, drawdown, per-position size, account/domain exposure, correlated event concentration when mapping exists, admission and reconciliation guards. Label limits read-only. Show denominator and units for utilization. Unknown valuation makes risk incomplete. The server's existing risk layer remains authoritative; charts never become admission logic.

Metric dictionary: realized P&L derives from closed/settled ledger events; unrealized derives from open positions with identified valuation source; net P&L subtracts recorded fees and incorporates funding exactly once under the domain ledger convention. If inputs or convention are absent, show unavailable and reason. Define session/day using selected display timezone, convert boundaries to UTC for queries, and label all exports. Return percentages require a documented capital denominator. Win rate uses resolved trades only; profit factor with no losses is undefined; drawdown specifies curve and period. Distinguish simulation estimates from realized execution.

Performance: equity and drawdown, daily results, strategy/instrument attribution, fees/slippage, trade count and holding times, all scoped and with sample size. Backtest train/test and validation evidence remain in Strategies, linked for comparison without joining curves. Journal includes execution/decision timeline plus optional local notes and tags attached to stable run/trade IDs. Export currently filtered CSV and a session summary with scope, timestamps, metric definitions, incomplete-data flags, and source IDs. Escape spreadsheet-formula prefixes in free text; omit secrets and private configuration.

### 6. Strategies and operations workflows

Strategy cards show name/version, supported domain, last run, gate state, paper status, sample size and next step. Details group Overview, Validation, Paper runs, Decisions, Evidence. Lab compares accounts side by side and preserves its current distinction from backtesting. Validation explicitly distinguishes insufficient history, not evaluated, failed, and passed. Gate progress lists concrete unmet requirements and evidence date; elapsed capture time alone cannot imply approval.

Council content is a secondary evidence view: inputs, verdict, rationale, artifact lineage, timestamps, and missing/stale evidence. It is never a buy button or a replacement for deterministic admission.

Operations Health summarizes capture, engine heartbeat, database/query availability, reconciliation, and job outcomes. Data retains feed-level coverage and sampling detail. Job actions show scope, prerequisites, running progress if reported, start/end times, result summary, and readable failure with expandable sanitized log. Existing allowlisted commands remain the sole executable job inventory. Do not accept arbitrary commands from forms. No auto-retry for mutations.

Alerts use stable type + scope + source identity for deduplication. Store first/last seen, severity, occurrence count, acknowledged time, resolved time, and target link. Acknowledgement does not resolve a condition or clear a guard. Derive feed staleness from feed-specific expected cadence/lifecycle; quiet closed markets are different from missing required data. In-app alerts are initial scope; email/SMS/push integrations are deferred.

### 6a. Whole-dashboard session authentication

Added 2026-09-14 to resolve `reconciliation.md` CONFLICT-1: `multi-venue-paper-trading`
requires the web halt to fail closed when dashboard authentication is absent;
this change requires a halt control visible on every view. Today
`dashboard_auth_secret` (`config/settings.py:264`) is checked only as a
bind-address guard in `scripts/start_dashboard.py` — it gates whether a
non-loopback `--host` is allowed at launch, not any individual request. No
route in `web/app.py` authenticates its caller. User decision (2026-09-14):
build real local request authentication rather than treat loopback binding as
the security boundary or ship halt as visible-but-unavailable.

**Mechanism.** An HttpOnly, `SameSite=Lax` (or `Strict` if it does not break
the auto-opened-browser bootstrap redirect; verify during implementation)
session cookie gates the **entire dashboard**, not only mutating routes.
Read-only pages carry the same risk of disclosing account state, positions,
and P&L as a control action, so scoping auth to POST routes only would leave
every GET route — including the ones this change adds — unauthenticated.

- **Session cookie.** Opaque, server-generated session token, HttpOnly,
  `Secure` when the connection is TLS (never on plain-HTTP loopback, since
  `Secure` would silently break the cookie there), `SameSite=Lax`, no
  client-readable value, no embedded claims — validated against a small
  server-side session store (in-memory is acceptable for a single local
  operator process; do not add a new persistent table unless session
  survival across a dashboard restart is explicitly wanted, which it is not
  by default. A restart requiring one new bootstrap redirect is the
  intended and simpler behavior).
- **Login.** There is no username/password. A session is established one of
  two ways:
  1. **Loopback one-click startup (default).** `scripts/start_dashboard.py`
     generates a random, single-use bootstrap token at process start,
     includes it as a query parameter on the URL it auto-opens in the
     browser (e.g. `http://127.0.0.1:8765/?bootstrap=<token>`), and the
     dashboard's root handler exchanges a valid, unused bootstrap token for
     a session cookie via a redirect to the bare URL (so the token never
     sits in browser history past that first load). The token is invalidated
     after first use and after a short TTL (a few minutes), whichever comes
     first, so a stale terminal scrollback or shared screen does not leave a
     standing credential. This preserves one-click startup exactly: the
     operator still runs the batch file and lands in an authenticated
     dashboard with no separate login step.
  2. **Non-loopback bind.** Already refuses to start without
     `DASHBOARD_AUTH_SECRET` set (`start_dashboard.py`'s existing guard).
     Once request auth exists, the same secret additionally gates session
     login for non-loopback access: a `/login` form (or equivalent) accepts
     the configured secret and, on match, issues the same session cookie.
     Constant-time comparison; no secret echoed in logs or error text.
- **Which routes require authentication.** All of them, with two narrow
  exceptions: the bootstrap-token exchange route itself (it establishes the
  session, so it cannot require one) and static asset paths (CSS/JS/icons
  with no account data). Every page route, every fragment/polling endpoint,
  and every mutation route requires a valid session. This is stricter than
  "mutations only" by design — see above.
- **Missing-secret / no-session behavior.** A request without a valid
  session cookie receives a redirect to the bootstrap/login flow for
  browser navigations, or `401 Unauthorized` for fragment/JSON polling
  requests (so `live.js`-style polling fails visibly as "disconnected"
  rather than silently rendering an empty authenticated-looking fragment).
  This is the fail-closed behavior `multi-venue-paper-trading` requires:
  with no valid session, nothing renders, including the halt control itself
  — satisfying that spec's literal wording without contradicting this
  change's "halt on every view" requirement, since "every view" presumes an
  authenticated view.
- **CSRF.** Session-cookie auth reopens CSRF risk that the current
  no-auth-at-all deployment does not have (there is nothing to forge a
  session for today). Every mutating route additionally requires a
  same-origin check (`Origin`/`Referer` header) plus a per-session CSRF
  token embedded in each rendered form and verified server-side on submit —
  satisfying task 4.4's existing CSRF/same-origin requirement using the new
  session as its anchor. A request with a valid session cookie but a
  missing/mismatched CSRF token is rejected before it reaches any control
  logic.
- **What this does not change.** No user accounts, no multi-user
  authorization model, no password storage, no remote hosting posture shift
  — this remains a single local operator's own machine. The session model
  exists to make "a request came from this operator's own browser, launched
  by this operator's own process" a checkable fact instead of an assumption,
  which is the minimum needed to wire a real halt control per CONFLICT-1.

**New task:** implementation is task 4.0 (`tasks.md`), sequenced in P0 (§10
below) rather than left at its original P1 position, since task 2.1's status
model and the shell's persistent halt header both need to know whether a
request is authenticated before they can be built against real enforcement
rather than a placeholder.

### 7. Truthful controls and state model

Separate execution mode, operator request, process status, heartbeat freshness, and entry permission. Example: `PAPER | Process running | Entries blocked: stale feed` is valid; a single green `Started` badge is insufficient. Expose `unsupported`, `stopped`, `starting`, `running`, `halt requested`, `halted`, `failed`, and `unknown` as applicable, with observation timestamps and reasons.

Start paper opens a review showing exact account/run/config, entry gates, and consequences. Server rechecks prerequisites on submission; UI disablement is supplementary. Duplicate start requests cannot launch duplicate processes. Dashboard GETs and refreshes never arm or launch. Reopening the dashboard never starts execution; show observed existing external processes rather than falsely reporting all trading stopped.

Global `Halt new entries` is one action without a confirmation dialog. Wire through existing emergency/governance machinery and acknowledge per target; verify whether that machinery reaches every managed paper runner before exposing a successful global result. Halt is sticky until explicit revalidated resume. It blocks new entries; it does not promise cancellation, liquidation, or flattening. Existing exits/reconciliation continue where the execution engine supports them. `Stop paper engine` is a separate process action with a clear warning about monitoring interruption and unresolved positions. If only intent state can be changed, label it as intent and do not advertise execution protection.

Controls use POST/redirect/GET, server-validated identifiers, same-origin/CSRF protection, idempotency tokens or equivalent operation deduplication, and audit records. Record request ID, target scope, action, timestamp, before/requested/observed state, result and error. Browser timeout means `Outcome unknown; checking status`, never automatic success or repeated action. Native forms work without JavaScript, but require a reachable server; remove the current misleading implication that a browser control works without network/server connectivity.

### 8. Technical architecture and data contracts

Retain FastAPI/Jinja and local CSS/JS; extract reusable template components and small read-model modules as `queries.py` grows. Prefer server-rendered HTML fragments over introducing React/SPA tooling. Use local SVG/small chart code or a vendored, license-reviewed chart dependency only if necessary; no runtime CDN or package install. URLs own filters and sort; server owns results and guard decisions; the browser owns transient drawer/focus state.

Each read model includes scope (`domain`, `venue`, `mode`, `account_id`, `run_id`), stable row ID, source timestamp, fetch timestamp, freshness (`fresh/stale/unknown`), availability (`available/partial/unavailable`) and reason. Money carries currency; prices carry cents/dollars/other quote units. Maintain canonical decimal/integer representation and round only for display. Do not conflate ingest time and exchange observation time.

| Read model | Source first | New work / unavailable behavior |
|---|---|---|
| DeskSnapshot / EngineStatus | Existing readiness, process snapshots, governance state, run summaries | One authoritative status service; no intent-as-heartbeat |
| MarketList / MarketDetail | Existing discovered instruments, persisted quotes, admission and signals | Capability audit for rules, depth, volume; absent fields explicit |
| PortfolioSnapshot / PositionDetail | Paper ledgers, perp position views, run reporting | Domain adapters and accounting tests; no invented cash balances |
| OrderFillHistory / DecisionDetail | Existing order tracker, fill/decision records, council artifacts | Stable joins, lifecycle coverage markers |
| StrategySummary / ValidationDetail | Existing lab comparison, backtest reports and promotion gate | Contextual links and shared status vocabulary |
| Alert / OperatorAction | Existing health/guard events plus new local records | Deduplication, acknowledgement and durable audit |
| WorkspacePreference / Watchlist / JournalNote | Existing theme settings plus additive local tables | Versioned schema, stable instrument references and notes |

Use additive storage migrations only. Preferences keyed by local profile and relevant scope; no authentication identity is invented. Store timezone, density, theme, table columns, watchlists; do not persist execution authorization in preferences. Validate unknown/retired instruments gracefully. Persist journal/alerts/actions server-side. Read queries use bounded pages (default 50, maximum 200) and whitelisted sorts. Audit query plans before indexing; no heavy backtest or coverage reconstruction inside a page request.

Refresh status at 5s, changing tables at 10s, historical analytics on filter/manual refresh. These are product targets, not exchange streaming guarantees. One in-flight request per panel, abort superseded requests, exponential backoff capped at 60s, pause hidden tabs, refetch on focus. After two failed status intervals show disconnected; retain last successful values with age. Freshness still uses the data source's own cadence. Never replace action forms during refresh. Detect older snapshot responses and discard them.

Local benchmark target: 100k historical decisions, 10k fills, 1k markets; initial desk usable within 2s, p95 bounded list/fragment response <=500ms on the documented test machine, no monotonic memory growth during 30 minutes monitoring. Report hardware/database size and cold versus warm runs. Polling cannot delay halt handling: isolate long jobs and bound query workloads. Acknowledgement latency is measured separately from HTTP acceptance.

### 8a. Resolving the task 2.1 blockers found by the P0 audit

`audit.md` §5 recorded five open questions rather than deciding them
unilaterally. Four are resolved here so task 2.1's status/snapshot read
models have a fixed contract to build against; one (OPEN-4, order-book depth
coverage) is deliberately deferred, per the sixth item below.

**OPEN-5 — durable runner heartbeat / process status.** Add a small,
additive `runner_heartbeats` table (or equivalent), written by each paper
runner process on a short interval (e.g. every poll cycle, matching the
runner's own loop cadence — no new scheduler, it rides the runner's existing
loop) and by the dashboard's own `PaperProcess`/`CaptureProcess` handles when
they hold a live subprocess reference. Columns: `run_id`, `pid`, `host`,
`observed_at` (heartbeat emission time), `available_at` (write time),
`process_kind` (`paper_runner|capture|other`). A row's absence or staleness
(no heartbeat within N× the runner's expected interval, mirroring
`FeedHealth`'s existing stale-factor pattern) is how the status model
distinguishes "running row, dead process" from "running and healthy" —
exactly the `disconnected_runner_state` fixture's scenario. This also
directly closes `audit.md` §3.6 item 4: an externally started runner (CLI,
prior dashboard instance) becomes observable the moment it writes its own
heartbeat row, without the dashboard needing to hold a process handle for it.
DeskSnapshot/EngineStatus (the read-model table above) source liveness from
this table, not from `paper_runs.status` alone.

**OPEN-2 — persisted guard-usage snapshots.** Add a `risk_guard_snapshots`
table (or extend `paper_audit_events` with a new `kind="guard_snapshot"`
row shape — prefer extending the existing audit-event mechanism over a new
table if the payload JSON can hold it cleanly, per `reconciliation.md`
OWN-2's instruction not to fork `multi-venue-paper-trading`'s ledger
ownership) written by each active guard (`DailyLossGuard`, drawdown,
consecutive-losses, per-position sizing) on each evaluation, carrying
current usage against its configured limit, `observed_at`, and the run it
applies to. The risk page (task 7.4) and desk risk tile (task 5.1) read the
latest snapshot per guard per run; absence of a recent snapshot renders
"usage unavailable" rather than blank or zero, consistent with the
capability matrix's existing unavailable-value convention. This is new
persistence, not a read-model trick — guard state today lives only in
runner process memory (`audit.md` §1.5) and cannot be recovered by any query
change alone.

**OPEN-1 — account identity, starting capital, and prediction-trade
attribution.** Resolved as option (b) from `audit.md` OPEN-1: add
`account_id` (defaulting to the run's own id where no coarser account
grouping exists yet — i.e. `account_id` starts as a 1:1 alias of `run_id`
and only diverges once a real multi-run-per-account concept is introduced,
which this change does not add) and `starting_capital_usd` to `paper_runs`,
plus a `paper_run_id` foreign key on `simulated_trades` so prediction-ledger
rows can finally be attributed to a run instead of returning the coarse
all-paper figure `queries.py:1165-1170` documents today. Per
`reconciliation.md` OWN-2, `paper_runs` and its ledger siblings are owned by
`multi-venue-paper-trading` — this is an additive migration proposed here
but implemented under that change's sign-off; task 2.1 should coordinate
rather than land it unilaterally if that change is still active. Until the
migration lands, `duplicate_paper_capital`-style comparisons continue to
render two separate rows with capital carried only in test fixtures /
operator knowledge, never summed — the existing honest behavior is not
blocked by this decision, only improved by it.

**OPEN-3 — stale liquidation price.** `PerpPositionView.liquidation_price`
is read once from the position's opening fill event and never recomputed
(`queries.py:1093`). Rather than either silently displaying a number that
drifts from reality as margin/mark change, or hiding it, the read model adds
the fill event's `observed_at` as a sibling field (`liquidation_price_as_of`)
and the UI labels the value "Liquidation estimate (as of open, not
recalculated)" with that timestamp, until a recalculation path exists. This
is a presentation/read-model decision, satisfiable in task 2.1/7.2 without
new persistence — the timestamp is already on the row, it is simply not
surfaced by `PerpPositionView` today.

**OPEN-4 — order-book depth coverage — explicitly deferred, not resolved
here.** Whether `order_book_snapshots` actually contains a depth ladder or
only top-of-book cannot be answered from the schema (`audit.md` §1.3); it
requires inspecting real captured rows. This is correctly scoped to task 6.4
(market-detail depth view), not task 2.1 — the snapshot/status read models
task 2.1 covers do not depend on depth data. Defer inspection to that task.

### 9. Responsive and accessibility behavior

At >=1280px use sidebar and two-column desk. At 768–1279px collapse navigation and use fewer metric columns. Below 768px stack panels, retain mode/state/halt in the visible header, and put risk/attention before lists. At 390px no page-level horizontal overflow; wide tables scroll within labeled regions with key columns pinned or use readable summaries. Full detail always remains available.

Support keyboard-only navigation, skip link, visible focus, correctly associated labels, `aria-sort`, accessible dialogs with focus return, semantic headings, and chart data tables. Changes use restrained live-region announcements for critical status only. At 200% zoom controls remain reachable. Shortcut help, if added, must avoid single-key trading actions; no shortcut submits a financial or process action.

### 10. Delivery priorities and acceptance

| Phase | Deliverables | Exit criteria |
|---|---|---|
| P0: trustworthy foundation | Source/capability audit, whole-dashboard session authentication (§6a), durable runner heartbeat/process-status source, status/control contract, read-model scoping, shell/tokens, freshness/error components | No intent labeled as execution; one-click launch and existing routes preserved (bootstrap-token exchange, not a manual login step); every route requires an authenticated session; runner liveness is evidenced by a real heartbeat, not run-row status alone; state tests pass |
| P1: daily trading workflow | Desk, market search/detail/watchlists, portfolio/orders/risk, supported paper controls | Operator locates risk/blocker in <=2 navigation actions; accounting fixtures reconcile; halt acknowledged from every view |
| P2: research and operations | Strategy/evidence links, health/jobs, alerts, journal/performance/export, preferences | Full decision-to-outcome path; duplicate/failed action tests; exports match scoped UI |
| P3: release hardening | Responsive/a11y/browser review, load profiling, migration/rollback rehearsal, documentation | All capability scenarios pass; screenshots reviewed at 390/768/1440px; no launch-time network assets |

All phases are required for this change; priority determines sequencing. Future live execution and external notifications are separate follow-up changes, not unfinished tasks hidden in this plan.

## Risks / Trade-offs

- Fragmented ledger semantics -> audit per domain, reconcile known fixture totals, keep unavailable values explicit.
- Existing global control is intent-only -> integrate and test the actual halt path before claiming protection; show unknown on missing acknowledgement.
- Broad UI scope -> release vertical slices in the phase order above; defer terminal customization and live tickets.
- Refresh can conceal failures or steal focus -> source ages, explicit errors, stable keys, read-only fragments and keyboard regression tests.
- Existing theme settings may reduce contrast -> migration mapping, measured presets and reset path.
- Related changes are still open -> reconcile `v2-perps-scalping-and-frontend`, `multi-asset-crypto-scalping`, `multi-venue-paper-trading`, `strategy-lab-multi-account`, `papertrading-readiness`, and `agentic-trading-council` contracts first; preserve authoritative execution requirements and avoid duplicate task ownership.
- A configured secret is not proof of request authentication -> resolved 2026-09-14 by §6a: whole-dashboard session authentication makes every request checkable, not only the launch-time bind-address guard. Local-only deployment remains the release scope; do not portray it as authenticated remote hosting.
- No durable evidence of runner liveness across the process boundary (`audit.md` OPEN-5) -> a status service built only on `paper_runs.status` cannot distinguish "running and healthy" from "running row, dead process" (see `audit.md` §3.6 item 4 and the `disconnected_runner_state` fixture). Add a durable heartbeat/process-status record before task 2.1's status model is built on top of it.

## Migration Plan

1. Inventory actual schema, execution capabilities, related-change deltas, and existing dashboard regression tests; document field-by-field availability and control targets.
2. Add read models and optional preference/audit tables with backward-compatible migrations; back up the local database before testing upgrades.
3. Introduce shared shell/components and route compatibility; replace overview and controls together so new chrome never advertises old intent as execution.
4. Implement vertical feature slices, keeping existing functionality reachable until replacement passes its scenarios.
5. Run focused integration/browser tests with isolated fixture databases and fake runners. Do not launch capture/trading against user data for visual testing.
6. Roll out via existing launcher after release checks. Rollback UI/routes to previous revision while retaining additive user data. Never roll back to a misleading successful halt display; preserve truthful controls or disable unsupported ones. Reverting UI must not reset execution guards or start a process.

## Open Questions

No user decision blocks planning. Defaults: single local operator, dark theme, comfortable density, latest paper account, machine timezone with visible UTC toggle, existing Python/Jinja stack. Implementation must resolve field coverage for prediction/sports orders, balance/mark availability, and whether emergency controls span all managed runners. Record results in a capability matrix before dependent views/controls ship; missing capabilities use the specified unavailable states. Revisit scope only if a new execution adapter or valuation policy is required.

## Model complexity

High overall: multi-file context, inconsistent state semantics, orchestration across reads and process mutations, ledger correctness, and cross-change dependencies. Planning is latency-tolerant; correctness takes priority over token savings. Bounded styling work can use faster/lower-cost models after contracts stabilize. No runtime LLM dependency is introduced.

| Stage | Recommended Codex allocation | Advisory Anthropic Pro allocation | Flexibility |
|---|---|---|---|
| Proposal and source audit | GPT-6 Astra | Claude Opus 5 | Retain full repository/context review |
| Design and specs | GPT-6 Astra | Claude Opus 5 | Strong allocation required for controls/accounting |
| Task decomposition and acceptance review | GPT-6 Astra | Claude Opus 5 | Keep cross-capability traceability in context |
| Bounded template/CSS implementation | GPT-6 Astra acceptable; GPT-5.6 Terra acceptable | Claude Sonnet 5 | Lighter choice only after contracts fixed |
| Ledger/control implementation and release review | GPT-6 Astra | Claude Opus 5 | Escalate any unresolved semantics or repeated failing scenario |

Current session uses GPT-6 Astra; no delegation or model switch is required for these artifacts. Anthropic allocations are advisory and were not executed. Model names checked 2026-09-14 against [official OpenAI model documentation](https://learn.chatgpt.com/docs/models), [Claude Opus](https://www.anthropic.com/claude/opus), and [Claude Sonnet](https://www.anthropic.com/claude/sonnet). Local session exposes GPT-6 Astra and GPT-5.6 Terra; actual account entitlement/usage limits must be checked in the account picker before a switch and are not inferred from API availability. Do not assume subscriptions include API billing.

Fallback: if Astra is unavailable, resume with the strongest account-available model after reading this checkpoint; Claude Opus 5 is the advisory alternative when user-selected access exists. Do not weaken control/accounting acceptance criteria. A lighter model must hand off after two failed attempts at the same integration scenario, ambiguous financial units, incompatible ledger IDs, or an execution-path change. Reassess allocation when scope/dependencies change.

## Checkpoint

Design complete; proposal dependency reviewed; four capability specs written;
tasks written. **2026-09-14 correction pass (post P0-audit):** the P0
capability-and-dependency audit (tasks 1.1-1.4, see `audit.md` and
`reconciliation.md`) surfaced findings that changed this design and the task
sequence before further implementation:

- Added §6a (whole-dashboard session authentication) and §8a (task 2.1
  blocker resolutions: runner heartbeat persistence, guard-usage snapshots,
  account identity/starting-capital/prediction-attribution migration,
  liquidation-price-as-of labeling; order-book depth coverage explicitly
  deferred to task 6.4).
- `tasks.md` gained task 4.0 (authentication) and task 2.0 (runner
  heartbeat), both moved into **P0** ahead of the shell/control work in
  section 3-4, since the status model (2.1) and the persistent header (3.2)
  both depend on real authentication and real liveness evidence existing
  first — see `tasks.md` for the renumbered sequence.
- `reconciliation.md` CONFLICT-1 (web halt vs. dashboard auth) is resolved
  by user decision: build real session authentication (§6a), not the
  loopback-as-boundary or visible-but-unavailable alternatives.
- Model allocation: "GPT-6 Astra"/"GPT-5.6 Terra" in this document's model
  tables are not applicable to the session executing this change — no such
  models are reachable from it. Treat the Anthropic column as the actual
  (not merely advisory) allocation: Claude Opus 5 for audit/control/ledger
  work, Claude Sonnet 5 for bounded presentation work once contracts are
  fixed, per this document's own escalation rule.

No implementation or runtime verification has been performed beyond the P0
audit's fixtures (`tests/unit/conftest_dashboard_states.py`,
`tests/unit/test_dashboard_state_fixtures.py`) and the regression baseline
recorded in `audit.md` §4.1 (986 passed / 0 failed before, 999 passed / 0
failed after the audit's own additions). Resume with `openspec status
--change trader-dashboard-experience --json`; the next task is the revised
P0 sequence in `tasks.md` (authentication, runner heartbeat, then the
original 2.1-2.5, 3.1-3.5), not task 1.1. Preserve completed artifacts.
Final readiness and verification are recorded in `handoff.md`.
