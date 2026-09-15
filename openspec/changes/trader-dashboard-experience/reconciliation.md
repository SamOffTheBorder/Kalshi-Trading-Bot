# Cross-Change Reconciliation

Task 1.2 of `trader-dashboard-experience`. Companion to [`audit.md`](./audit.md).

Purpose: record what each overlapping change **owns**, so later tasks in this
change do not duplicate, contradict, or silently override an authoritative
requirement. Ownership decisions below are recorded as decisions; genuine
contradictions are escalated rather than resolved unilaterally.

---

## 0. Living capability files — explicit confirmation

**Confirmed: `openspec/specs/` contains zero files.**

Verification: `ls -la openspec/specs/` returns only `.` and `..`;
`find openspec/specs -type f` returns nothing.

This confirms `proposal.md:27` is still accurate. Consequences:

- No MODIFIED-requirement work is possible in this change. All four specs
  correctly use `## ADDED Requirements` only.
- Every requirement cited below lives in an **unarchived change**, not in a
  living spec. None of them is yet the repository's settled contract — they are
  competing proposals. "Ownership" here means *which change's task list should
  implement it*, not *which spec is law*.
- Because no spec is archived, there is no automated conflict detection. This
  document is the only record that these overlaps exist.

---

## 1. Ownership register

### OWN-1 — `v2-perps-scalping-and-frontend` → `operator-dashboard`

**Owns:** the six foundational dashboard invariants
(`specs/operator-dashboard/spec.md`): single-action launch with no build step
(:5), trading starts stopped (:12), kill switch always reachable (:19), decisions
including HOLDs visible (:26), risk state visible at a glance (:33), not exposed
beyond loopback without a secret (:40).

**Decision:** v2 is **authoritative** for all six. `trader-dashboard-experience`
**preserves and re-expresses** them; it must not weaken any.

Mapping (this change's spec → v2's requirement it preserves):
- `trader-workspace:38` (local launch, bounded reads) preserves v2 :5 and :40.
- `trader-operations-workflow:3` (capability-derived engine state) preserves
  v2 :12 — "Starting or reopening the dashboard SHALL NOT launch trading" is
  strictly stronger than v2's wording, which is acceptable.
- `trader-operations-workflow:17` (acknowledged global entry halt) is the
  **contested** one — see CONFLICT-2.
- `trader-market-discovery:24` (explainable assessments, HOLD reasons) preserves
  v2 :26.
- `trader-portfolio-review:24` (visible risk policy and usage) preserves v2 :33.

**Note on v2 :33.** It requires "open positions with unrealized PnL... daily PnL
against the loss limit". Per `audit.md` §1.1 and §1.5, **neither is available**
today. v2 states this as a requirement; this change's audit finds no source.
This is not a contradiction between the changes — it is an unimplemented v2
requirement that this change has now costed. Recorded as `audit.md` OPEN-2.

### OWN-2 — `multi-venue-paper-trading` → paper ledgers, governance, operator commands

**Owns (and this change must not reimplement):**
- `paper_runs`, `paper_audit_events` (`storage/models.py:510-558`) — run identity
  and the append-only audit trail.
- `emergency_halt_records` + `GlobalEmergencyControl`
  (`models.py:1208-1235`, `risk/governance.py:93-152`) — the durable halt ledger,
  per `specs/cross-domain-risk-governance/spec.md:25` ("Unified emergency halt
  and resumption").
- `lifecycle_transition_records` (`models.py:1237-1266`) — promotion/demotion,
  per `cross-domain-risk-governance/spec.md:36`.
- The **command line as canonical execution entry point**
  (`paper-trading-operations/spec.md:47`).
- Domain-first areas: Prediction Markets, Perpetuals, Sports plus an all-domain
  overview (`paper-trading-operations/spec.md:3`).

**Decision:** multi-venue is **authoritative** for the halt/resume *mechanism*
and the *ledger schema*. `trader-dashboard-experience` task 4.2 must **wire the
web tier into `GlobalEmergencyControl`**, and must **not** invent a second halt
store. Any new column on `paper_runs` (see `audit.md` OPEN-1) is a multi-venue
schema change and needs its sign-off, not a unilateral migration here.

**Route overlap, resolved:** multi-venue owns the *existence* of domain areas;
this change owns their *information architecture* (`design.md:32-41`). This
change explicitly retains `/sports`, `/perps`, `/prediction-markets`
(`design.md:35`), which are implemented at `web/app.py:273-283`. No conflict —
this change adds `/markets` as a parent and keeps the three as children.

### OWN-3 — `multi-asset-crypto-scalping` → `operator-dashboard` (asset/mode axis)

**Owns:** asset- and cadence-aware operational status (:3), portfolio-risk
visibility including correlation-group usage (:14), honest mode display
distinguishing observe/backtest/paper/live (:23).

**Decision:** multi-asset is **authoritative** for the *asset lifecycle
vocabulary* (`observe|backtest|paper|live`, plus `shadow` and `blocked` from
multi-venue and papertrading-readiness) and for *correlation-group risk*.
`trader-dashboard-experience` must **reuse** that vocabulary in its mode badge
(`design.md:41`: "PAPER / SHADOW / BACKTEST / LIVE badge") rather than define a
parallel one.

**Important constraint this change must honour:** multi-asset :23 requires that
an observation-only asset **SHALL NOT** be given an arm/trade control
("ZEC is observation-only" scenario, :30-33). This change's persistent halt/start
header (`design.md:41`) must therefore be **scope-aware** — a global start
control that ignores per-asset lifecycle would violate multi-asset :23.

**BREAKING flag noted:** multi-asset declares "former BTC-named dashboard/query
interfaces become generic crypto-asset interfaces". `queries.py` still contains
BTC-named surfaces (`cached_btc_coverage` at `queries.py:550`,
`brti_reconstruction_coverage` at `:591`). This change must not entrench
BTC-specific naming in new read models.

### OWN-4 — `strategy-lab-multi-account` → run comparison and per-run keying

**Owns:** the strategy registry (`strategy_id`/`strategy_config_version`/
`strategy_gate_status`, live at `models.py:533-536`), the multi-account launcher,
and — directly relevant here — **"dashboard sections for perpetuals and
15-minute scalping, with a side-by-side comparison view keyed by `paper_run_id`,
and per-run controls."**

**Implemented already:** `/strategy-lab` (`web/app.py:285-296`),
`strategy_lab_comparison` (`queries.py:1188-1211`), `LabAccountComparison`
(`queries.py:1120-1136`), `perp_positions_view` (`queries.py:1068-1118`).

**Decision:** strategy-lab is **authoritative** for run-vs-run comparison and for
the rule that "paper evidence never silently upgrades a strategy's standing" —
encoded in the code comment at `queries.py:924-929` and the model docstring at
`models.py:533-537`. `trader-dashboard-experience` task 8.1 ("Restructure
Strategies/Lab") must **preserve `strategy_gate_status` semantics unchanged** and
must not let a good paper P&L render as a passed gate.

**Direct overlap with this change's task 7.5** ("Verify account comparisons never
sum duplicate experimental capital"): strategy-lab already built the comparison
**as a table keyed by run id**, which is exactly the shape
`trader-portfolio-review:4-8` demands ("comparison shows separate results and
does not present their sum"). **Decision: do not rebuild it.** Extend
`strategy_lab_comparison` rather than create a second comparison read model.

**Known defect inherited, not owned:** `_run_net_pnl` returns a coarse all-paper
figure for prediction runs because `SimulatedTrade` has no run key
(`queries.py:1165-1170`, and `audit.md` §1.4). Fixing that is a **schema** change
in multi-venue's territory (OWN-2), surfaced by strategy-lab. This change should
**display the limitation honestly**, not paper over it, until OPEN-1 is decided.

### OWN-5 — `papertrading-readiness` → readiness matrix and lifecycle plumbing

**Owns:** the `shadow` lifecycle literal, `scripts/freeze_manifest.py`,
`scripts/discover_crypto_perps.py`, `--domain sports` wiring, and **"Publish a
readiness matrix (dashboard panel or doc, reusing the `market_area.html`
admission table pattern)"**.

**Implemented already:** `papertrading_readiness` (`queries.py:202`),
`PaperTradingReadiness` (`queries.py:92-140`), rendered via `markets.html` and
`market_area.html` (`app.py:231,251`).

**Decision:** papertrading-readiness is **authoritative** for the readiness
matrix's *content and per-domain prerequisite semantics*.
`trader-dashboard-experience` owns *where it appears* in the new IA — the design
places readiness under Operations and the setup journey
(`design.md:38`, `design.md:89`). **Decision: relocate/reskin, never redefine.**
The prerequisite list stays papertrading-readiness's.

Direct dependency: this change's task 5.4 ("initial setup journey linking
configuration, capture, validation and reviewed paper start") is essentially the
readiness matrix rendered as a journey. It must read the same query.

### OWN-6 — `agentic-trading-council` → council evidence

**Owns:** `council_runs`, `council_evidence_bundles`, `council_agent_definitions`,
`council_agent_verdicts`, `council_decisions`, `council_profile_lifecycle`
(`models.py:560-707`), and the authority boundary in
`deterministic-agent-admission`: council output **never** overrides deterministic
admission, safety, or risk gates, and **never** enables live execution.

**Implemented already:** `/council` (`app.py:298-314`), `council_run_details`
(`agents/inspection.py`), `templates/council.html`.

**Decision:** council is **authoritative** for verdict/evidence shape and for the
authority boundary. `trader-dashboard-experience` already agrees —
`design.md:119`: "It is never a buy button or a replacement for deterministic
admission." **No conflict.** This change's contribution is navigation: council is
currently reachable by route but absent from primary navigation
(`design.md:10`), and this change moves it under Strategies as a secondary
evidence view (`design.md:37`).

---

## 2. Conflicts

### CONFLICT-1 — Web halt vs. dashboard authentication *(resolved 2026-09-14 — user decision)*

**Severity when found: blocking for task 4.2 as originally written. Resolved
below; task 4.2 now depends on task 1a.1 instead of being blocked outright.**

- `multi-venue-paper-trading/specs/paper-trading-operations/spec.md:47`:
  "The website SHALL be read-only by default. If a local authenticated operator
  control is implemented for halt/resume... it SHALL... **fail closed when
  dashboard authentication is absent**." Scenario at :51-53: "**WHEN** dashboard
  authentication is absent or invalid **THEN** the website SHALL not expose or
  execute a halt, resume, or run-control action."
- `trader-dashboard-experience/specs/trader-operations-workflow/spec.md:18`:
  "A supported `Halt new entries` control SHALL exist on **every view** and
  invoke the actual emergency/governance path in one action."

**Why this actually bites:** `dashboard_auth_secret` defaults to `None`
(`config/settings.py:264`) and authenticates **nothing** — it is checked only as
a bind-address guard in `scripts/start_dashboard.py:40-47`. There is no request
authentication anywhere in `web/app.py` (`audit.md` §3.5). So under multi-venue's
literal rule, the correct behaviour on a default local install is to **not expose
the halt control at all** — the opposite of "on every view".

There is also a second-order conflict: multi-venue keeps the **command line as
the canonical execution entry point** (:47), while this change's whole premise is
a trustworthy *web* control surface.

**Resolved by user decision (2026-09-14): implement real local request
authentication before task 4.2's halt wiring lands.**

Three candidate resolutions were presented:
1. Treat loopback binding as the authentication boundary and amend multi-venue's
   wording to say so explicitly.
2. Implement real local request auth, satisfying both literally.
3. Ship halt as **visible but explicitly unavailable** until (1) or (2).

**User selected option 2.** `dashboard_auth_secret` (`config/settings.py:264`)
already exists as a setting but is enforced nowhere in `web/app.py` — it is
checked only as a bind-address guard in `scripts/start_dashboard.py:40-47`.
This added scope beyond `tasks.md`'s original 50 tasks. Applied: whole-dashboard
session authentication is specified in `design.md` §6a and
`specs/trader-operations-workflow/spec.md` ("Whole-dashboard session
authentication"), and implemented as task **1a.1**, sequenced in **P0** —
ahead of task 4.2, not merely before it within P1 — since task 2.1's status
model and task 3.2's persistent header both need real authentication to build
against. Task 4.2 now explicitly depends on 1a.1 landing first (`tasks.md`).
This changes the deployment/security model: the dashboard becomes
authenticated (whole-dashboard session cookie, bootstrap-token login for
one-click loopback startup) rather than trust-the-loopback, with its own
acceptance criteria in the spec scenarios above.

**Status: resolved, not escalated.** Do not ship an exposed, working,
unauthenticated halt, and do not substitute option 1 or 3 for this decision
without checking back in — but no further user input is needed to proceed
with implementation; the design and task are specified and ready.

### CONFLICT-2 — "Kill switch" semantics: stop vs. halt-new-entries

- `v2/specs/operator-dashboard/spec.md:19-24`: "A halt control SHALL be present
  on every dashboard view and SHALL **stop new entries** and trigger the
  emergency-control path in one action... **THEN** new entries stop immediately."
- `trader-operations-workflow:18`: halt "SHALL NOT claim to cancel or flatten
  positions", and process stop "SHALL be separately labeled".

**Assessment: compatible in substance, incompatible in current UI copy.** Both
mean *stop new entries*. But the shipped UI labels the control a "kill switch"
(`web/control_state.py:1`, `templates/_control_status.html:6` renders
"STOPPED — kill switch"), which reads as "everything stopped" — precisely the
misleading framing this change exists to remove (`proposal.md:13`).

**Decision:** `trader-dashboard-experience` is **authoritative for the
vocabulary**; v2 remains authoritative for the *reachability* invariant (every
view). Rename to `Halt new entries`, keep it on every view, and label process
stop separately. This satisfies v2's scenario while fixing the copy. Recorded so
task 3.2/4.3 does not re-litigate it.

### CONFLICT-3 — v2 "Risk state visible at a glance" vs. actual data availability

v2 :33 requires unrealized P&L, guard state, and daily P&L against the loss
limit. `audit.md` §1.1/§1.5 finds **none of these has a readable source** across
the process boundary.

**Assessment: not a spec-vs-spec conflict — a spec-vs-reality gap.** Recorded so
that task 5.1/7.4 renders these as unavailable-with-reason rather than either
(a) inventing values, or (b) being marked as violating v2. Tracked as `audit.md`
OPEN-2.

### CONFLICT-4 — Global start control vs. per-asset lifecycle

`design.md:41` puts a global start/halt in the persistent header;
`multi-asset-crypto-scalping/specs/operator-dashboard/spec.md:23-33` forbids
presenting an arm/trade control for an observation-only asset.

**Decision:** the header control must be **scope-aware and capability-derived** —
which `trader-operations-workflow:3` already demands. No spec change needed;
recorded as an implementation constraint on task 3.2 so a global button is not
added naively.

---

## 3. Non-conflicts worth recording

- **Sports.** multi-venue requires Sports to display research-only/disabled until
  its gate passes (`paper-trading-operations/spec.md:9-12`). This change adds no
  sports execution. `audit.md` §1.1 confirms there is no sports ledger at all, so
  a sports portfolio view must state "unavailable", not render empty. Consistent.
- **No live execution anywhere.** All seven changes agree. This change reinforces
  it (`design.md:41`: "Live views display `Execution unavailable`").
- **Foreground-only, no schedulers.** Agreed across changes. Note `web/app.py:163`
  starts a **daemon background thread** for the coverage cache refresh loop
  (`app.py:154-163`). This is a read-only cache warmer inside the dashboard
  process, not a trading scheduler — it does not violate the rule, but task 3.4's
  polling work should not extend it into anything that mutates state.
- **Additive migrations.** `storage/migrations.py` is additive and
  `PRAGMA user_version`-gated at `SCHEMA_VERSION = 16` (`migrations.py:7,70-165`).
  Compatible with `design.md:151`.

---

## 4. Summary of ownership decisions

| Area | Authoritative change | This change's role |
|---|---|---|
| Launch, starts-stopped, loopback, HOLD visibility | `v2-perps-scalping-and-frontend` | Preserve, re-express |
| Halt/resume mechanism + halt ledger schema | `multi-venue-paper-trading` | Wire web tier in; never fork |
| Run/audit ledger schema | `multi-venue-paper-trading` | Read only; schema changes need sign-off |
| Asset lifecycle vocabulary, correlation risk | `multi-asset-crypto-scalping` | Reuse vocabulary |
| Run-vs-run comparison, gate-status semantics | `strategy-lab-multi-account` | Extend, don't rebuild |
| Readiness matrix content | `papertrading-readiness` | Relocate/reskin only |
| Council evidence + authority boundary | `agentic-trading-council` | Navigation placement only |
| Dashboard IA, visual system, freshness/availability contract, control **vocabulary** | **`trader-dashboard-experience`** | Owns |

**CONFLICT-1 resolved 2026-09-14** (§2, "Web halt vs. dashboard
authentication") — session authentication, task 1a.1, P0. No cross-change
item currently requires a user decision.
