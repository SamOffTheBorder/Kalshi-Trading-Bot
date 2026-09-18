## 1. P0 — capability and dependency audit

- [x] 1.1 Map every proposed field to actual storage/query sources by domain; record unavailable fields, money units, capital identity and valuation conventions in a capability matrix.
- [x] 1.2 Reconcile overlapping dashboard, paper, strategy-lab, readiness and council changes; record ownership and preserve existing execution requirements.
- [x] 1.3 Trace paper start, entry halt, resume, process stop and emergency acknowledgement through actual runners; document supported target scope and unresolved paths.
- [x] 1.4 Create isolated fixtures for fresh/stale/empty/partial/error states, duplicate paper capital, partial fills and disconnected runners; establish the current dashboard regression baseline.

## 1a. P0 — authentication and runner observability (prerequisites for 2.1 and 3.2)

Added 2026-09-14 in the correction pass following the P0 audit. Originally
task 4.0 sat in P1's control-work section (4), too late: task 2.1's status
model and task 3.2's persistent header both need real authentication and real
runner-liveness evidence to build against, not a placeholder. Moved here so
implementation does not build a status/header contract around a fiction, then
have to retrofit it. See `design.md` §6a (authentication) and §8a
(OPEN-5 heartbeat resolution) and `reconciliation.md` CONFLICT-1.

- [x] 1a.1 Implement whole-dashboard session authentication: HttpOnly/SameSite session cookie gating every route (bootstrap/login exchange and static assets excepted); single-use short-TTL bootstrap token issued at loopback launch in a URL fragment and exchanged automatically so one-click startup needs no manual login or token-bearing access-log URL; non-loopback bind requires both configured TLS and `DASHBOARD_AUTH_SECRET` and uses it for session login; unauthenticated requests fail closed (redirect for navigations, 401 for fragments/polling) rendering no account data or controls; same-origin + per-session CSRF token required on every mutating route. Resolves `reconciliation.md` CONFLICT-1. See `design.md` §6a and `specs/trader-operations-workflow/spec.md` "Whole-dashboard session authentication".
- [ ] 1a.2 Add a durable runner heartbeat / process-status record (written by paper runner and capture processes on their own existing loop cadence, and by the dashboard's process handles where live) so a status model can distinguish "running row, dead process" from "running and healthy" across the process boundary, closing `audit.md` OPEN-5 and making externally started runners (CLI, prior dashboard instance) observable without a held process handle. See `design.md` §8a.

## 2. P0 — read contracts and durable state

- [ ] 2.1 Implement scoped snapshot/status read models with stable IDs, source/fetch timestamps, availability reasons and separate intent/process/entry-permission states. Sources runner liveness from task 1a.2's heartbeat record, not `paper_runs.status` alone. Resolves `audit.md` OPEN-1 (account identity: add `account_id`/`starting_capital_usd` to `paper_runs` and `paper_run_id` to `simulated_trades`, coordinated with `multi-venue-paper-trading` per `reconciliation.md` OWN-2), OPEN-2 (guard-usage snapshots: persist current usage per guard per evaluation, read as "unavailable" absent a recent snapshot), and OPEN-3 (liquidation price: expose `liquidation_price_as_of` and label it as an opening-fill estimate until recalculation exists) as recorded in `design.md` §8a. OPEN-4 (order-book depth coverage) is explicitly deferred to task 6.4, not resolved here.
- [ ] 2.2 Add backward-compatible migrations for local preferences/watchlists with theme mapping and validated defaults; verify existing settings survive.
- [ ] 2.3 Add durable operator-action and alert records with deduplication keys, acknowledgement/resolution fields and a migration round-trip check.
- [ ] 2.4 Add journal note/tag storage tied to stable run/trade IDs; validate missing and deleted references.
- [ ] 2.5 Implement bounded pagination, whitelisted sorts and compatible-account selection helpers; test account/mode/run isolation.

## 3. P0 — shell and visual system

- [ ] 3.1 Implement shared tokens, typography, metric/status/table/form components and measured dark/light presets while preserving custom themes.
- [ ] 3.2 Build six-section navigation, persistent scope/status/alert/halt header, breadcrumbs and compatible legacy URLs.
- [ ] 3.3 Implement responsive sidebar/stacked layouts, density and timezone preferences, reset and accessible focus/dialog behavior.
- [ ] 3.4 Replace refresh client with bounded read-only polling, timestamps, backoff, stale/disconnected UI and out-of-order response protection.
- [ ] 3.5 Verify shell scope persistence, keyboard navigation, JavaScript-disabled forms and first-launch onboarding states.

## 4. P1 — trustworthy paper controls

- [ ] 4.1 Implement reviewed start flow showing exact account/run/config and server-side gate revalidation; reject stale scopes and duplicate starts.
- [ ] 4.2 Wire entry halt to supported emergency/governance targets with durable request IDs and observed acknowledgements; keep unsupported paths explicitly unavailable. Depends on task 1a.1 (session authentication) landing first — see `design.md` §6a and `reconciliation.md` CONFLICT-1.
- [ ] 4.3 Implement sticky halt/resume semantics using existing risk policy and distinguish process stop from entry halt in UI and audit history.
- [ ] 4.4 Protect mutations with CSRF/same-origin validation, server-side IDs and deduplication; handle lost responses with outcome lookup.
- [ ] 4.5 Test halt from every view, missing/partial acknowledgements, concurrent starts, restart behavior and that GET/refresh never launches trading.

## 5. P1 — Trading Desk

- [ ] 5.1 Build desk summary tiles from a shared scoped snapshot with explicit unavailable/partial capital, P&L and risk states.
- [ ] 5.2 Build critical-first attention queue with relevant next-step links and compact healthy state.
- [ ] 5.3 Add bounded positions/watchlist/decisions panels with metric and record drilldowns; expose HOLD reasons.
- [ ] 5.4 Add initial setup journey linking configuration, capture, validation and reviewed paper start without automatic mutations.
- [ ] 5.5 Verify observed running-but-blocked state and contradictory legacy copy removal; check essential information above the fold at 1440x900.

## 6. P1 — market discovery and detail

- [ ] 6.1 Implement market list search, supported filters, stable sorting/pagination, column selection and watchlists with URL-backed state.
- [ ] 6.2 Build domain-specific quote rows with explicit cents/currency units, side labels, source age and missing-field behavior.
- [ ] 6.3 Build market detail with contract/event identity, close versus settlement lifecycle, recorded rules/source and related positions/decisions.
- [ ] 6.4 Add labeled price charts with gaps/table alternatives and real recorded liquidity only; display unavailable depth when absent.
- [ ] 6.5 Build signal evidence detail with price/fee/slippage basis, net edge units, sizing constraints and HOLD/gate reasons; verify no order submission is introduced.

## 7. P1 — portfolio and execution review

- [ ] 7.1 Implement separate domain ledger adapters and reconciled realized/unrealized/net P&L fixtures including fees, funding, partial marks and undefined ratios.
- [ ] 7.2 Build positions table/details with valuation age and domain-appropriate risk, settlement/funding fields and source lineage.
- [ ] 7.3 Build order/fill history with status/time/strategy filters, partial-fill/reject handling and explicit lifecycle coverage.
- [ ] 7.4 Build risk page showing recorded limits/usage and entry guards with denominator/units; retain read-only policy.
- [ ] 7.5 Verify account comparisons never sum duplicate experimental capital or mix modes, and that linked detail routes enforce the same scope.

## 8. P2 — strategies and operations

- [ ] 8.1 Restructure Strategies/Lab with version/domain/run summaries and separate backtest versus paper evidence classes.
- [ ] 8.2 Add validation checklist and decision/council drilldowns preserving insufficient/not-evaluated/failed/passed distinctions and HOLD lineage.
- [ ] 8.3 Build health/capture views with source-specific freshness, coverage, sampling and reconciliation context.
- [ ] 8.4 Build allowlisted job review/status/result views with sanitized errors and relevant recovery links; reject arbitrary job commands.
- [ ] 8.5 Implement deduplicated critical-first alerts with acknowledgement separate from guard resolution and opt-in local sound preferences.

## 9. P2 — journal analytics and preferences

- [ ] 9.1 Build scoped performance charts and attribution with sample sizes, capital denominator, window, timezone and metric definitions.
- [ ] 9.2 Build journal timeline, local notes/tags and decision-to-outcome navigation.
- [ ] 9.3 Implement scoped CSV and session-summary export with source IDs, units, incomplete flags and formula-prefix sanitization.
- [ ] 9.4 Complete Settings display preferences, connection capability status and read-only risk/validation explanations.
- [ ] 9.5 Verify filters persist through drilldowns/exports, UTC conversion across daylight-saving boundaries, and export totals match ledger fixtures.

## 10. P3 — release verification and handoff

- [ ] 10.1 Run existing dashboard regressions and all new capability scenarios with isolated databases/fake runners; record results and scenario-to-test mapping.
- [ ] 10.2 Review screenshots and keyboard flows at 390px, 768px and 1440px plus 200% zoom; verify contrast, reduced motion, labels, focus and chart alternatives.
- [ ] 10.3 Measure desk/list/fragment budgets on the documented large fixture and 30-minute monitoring session; ensure slow reads/jobs do not block halt handling.
- [ ] 10.4 Rehearse one-click batch startup without external asset access, additive migration/rollback and existing bookmarked routes; confirm no automatic trading.
- [ ] 10.5 Document pre-session checks, modes, halt versus stop semantics, missing-data states, metric definitions and post-session review in project help.
- [ ] 10.6 Perform final control/ledger review under the recommended strong model, resolve open capability dependencies, and update handoff with validation evidence.

## Model complexity

Follow `design.md` allocation. **2026-09-14 correction:** the "GPT-6
Astra"/"GPT-5.6 Terra" names in `design.md`'s table are not reachable from
the Claude Code session executing this change; treat the Anthropic column as
the actual allocation, not merely advisory — Claude Opus 5 for decomposition,
control/ledger implementation and final review; Claude Sonnet 5 for bounded
presentation work once contracts stabilize. Escalate on ambiguous units/IDs,
execution-path changes or two failures of the same integration scenario. All
phases remain required; no live execution or external notification
integration is included.

## Checkpoint

Planning artifacts complete. **2026-09-14: P0 audit done (tasks 1.1-1.4,
checked above); correction pass applied.** Design blockers the audit
surfaced are now resolved in `design.md` §6a/§8a and reflected here as new
tasks 1a.1 (session authentication) and 1a.2 (runner heartbeat), sequenced in
P0 ahead of the original section 2-4 work; task 4.0's authentication work was
relocated to 1a.1 rather than left at its original P1 position. Model
allocation follows the Anthropic column directly (Claude Opus 5 for
audit/control/ledger, Claude Sonnet 5 for bounded presentation work) — the
"GPT-6 Astra"/"GPT-5.6 Terra" references in this file and `design.md` are not
applicable to the session executing this change.

**Task 1a.1 is complete. Next task is 1a.2 (runner heartbeat), then the
original 2.1-2.5.** Not task 1.1 — that section is done. Resume using
`openspec status --change trader-dashboard-experience --json` to confirm
checkbox state, then `audit.md` and `reconciliation.md` for the findings
those new tasks close. Preserve completed tasks/artifacts across model
switches.

