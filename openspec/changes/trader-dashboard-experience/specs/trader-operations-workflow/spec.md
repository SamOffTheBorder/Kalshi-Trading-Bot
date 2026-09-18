## ADDED Requirements

### Requirement: Whole-dashboard session authentication

Every dashboard route SHALL require a valid authenticated session, established
via an HttpOnly, `SameSite` session cookie. Only no-data bootstrap/login session
establishment endpoints and static assets carrying no account data are exempt.
Loopback one-click startup SHALL establish a session automatically via a
single-use, short-TTL bootstrap token issued at launch and exchanged for a
session cookie on first load, without requiring a manual login step. A
non-loopback bind SHALL require both `DASHBOARD_AUTH_SECRET` and configured TLS
at launch and SHALL additionally require the secret to establish a session. A
loopback bootstrap token SHALL be conveyed in a URL fragment and exchanged by
POST so it is absent from HTTP request URLs and normal access logs. A request without a
valid session SHALL render no account data and no control, including the halt
control, and SHALL fail closed rather than expose a partially-authenticated
view. Every mutating route SHALL additionally require a same-origin check and
a per-session CSRF token verified before any control logic runs.

#### Scenario: One-click startup remains one click
- **WHEN** the operator launches the dashboard via the existing batch launcher on loopback
- **THEN** the auto-opened browser lands in an authenticated session with no separate login step, the bootstrap token is invalidated after first use, and the token is absent from the HTTP request URL and access log

#### Scenario: Non-loopback transport is incomplete
- **WHEN** an operator requests a non-loopback bind with a dashboard secret but without configured TLS
- **THEN** startup refuses before serving any dashboard route or accepting the secret over plain HTTP

#### Scenario: Unauthenticated request is refused, not partially rendered
- **WHEN** a request arrives with no valid session cookie
- **THEN** a browser navigation is redirected to the bootstrap/login flow and a fragment/polling request receives 401, and in both cases no account data, position, P&L, or control — including the halt control — is rendered

#### Scenario: Mutation without a matching CSRF token
- **WHEN** a POST request carries a valid session cookie but a missing or mismatched CSRF token
- **THEN** the request is rejected before any control or ledger logic runs, and no state changes

### Requirement: Capability-derived engine state
Controls SHALL distinguish operator intent, process state, heartbeat, entry permission and mode, with observation time and explicit unsupported/unknown states. Starting or reopening the dashboard SHALL NOT launch trading. Already-running external processes SHALL be reported only from observed evidence.

#### Scenario: Intent armed without process
- **WHEN** operator intent is armed but no execution heartbeat or running process is observed
- **THEN** the UI does not report Trading running and identifies the intent and missing execution evidence separately.

### Requirement: Reviewed and revalidated paper start
Starting paper execution SHALL show target account/run/config and prerequisites, require an explicit reviewed submission, revalidate server-side and prevent duplicate process launches. A data-view mode selector SHALL NOT start live execution.

#### Scenario: Gate changes during review
- **WHEN** readiness passes when review opens but fails before submission
- **THEN** the server rejects start with the current blocker and launches no process even if the browser still displays the earlier ready state.

### Requirement: Acknowledged global entry halt
A supported Halt new entries control SHALL exist on every view and invoke the actual emergency/governance path in one action, record scope and acknowledgements, and stay halted until explicit revalidated resume. It SHALL NOT claim to cancel or flatten positions. Unsupported paths SHALL be labeled unavailable; process stop SHALL be separately labeled.

#### Scenario: Runner fails to acknowledge halt
- **WHEN** one targeted runner fails to acknowledge a halt request
- **THEN** the UI shows partial/unknown completion per target and a critical attention item, records the request, and never reports all trading halted.

### Requirement: Reliable mutation handling
Mutation routes SHALL use POST with server validation, CSRF/same-origin protection, deduplication and audit records. Native form actions SHALL function without JavaScript when the server is reachable. Unknown network outcomes SHALL trigger status inspection without automatic retries or success claims.

#### Scenario: Response lost after accepted start
- **WHEN** a start request is accepted but the response is lost and the same operation is submitted again
- **THEN** the operation is deduplicated, no second runner launches, and the operator can inspect the recorded outcome.

### Requirement: Actionable readiness and evidence
Strategies SHALL expose version/domain, gate status, run history and next step; validation SHALL distinguish insufficient data, not evaluated, failed and passed. Decisions including HOLDs SHALL link to recorded strategy/council evidence and outcome. Lab and backtest results SHALL retain their distinct execution/evidence classes.

#### Scenario: Validation history sufficient but test fails
- **WHEN** capture reaches the required history but validation fails
- **THEN** the UI shows failed validation with the evidence and next step rather than marking the strategy ready from capture progress alone.

### Requirement: Health jobs and recovery
Operations SHALL expose feed cadence/freshness, engine/reconciliation health and allowlisted jobs with prerequisites, timestamps, reported progress, result and sanitized error detail. No arbitrary shell command SHALL be accepted from the UI. Job failures SHALL provide a relevant recovery action.

#### Scenario: Failed validation job
- **WHEN** an allowlisted validation job exits unsuccessfully
- **THEN** the job shows failed with available diagnostic detail and links to affected evidence without silently retrying or displaying success.

### Requirement: Durable deduplicated attention
Alerts SHALL record severity, affected scope, first/last seen, source identity, occurrence count, acknowledgement and resolution separately, sorted critical-first with actionable links. Acknowledgement SHALL NOT clear underlying guards. Initial delivery SHALL use in-app notifications only.

#### Scenario: Repeated stale-feed alert acknowledged
- **WHEN** the same feed condition recurs after the operator acknowledges it
- **THEN** one condition record updates its occurrence/last-seen data, remains unresolved until recovery, and the associated entry guard stays active.

## Model complexity

High-complexity cross-capability contract. Follow the model allocation and escalation rules in `../../design.md`: GPT-6 Astra for requirements and control/accounting review; Claude Opus 5 is an advisory user-selected alternative. Bounded presentation work can use the documented lighter allocation only after contracts are fixed. Revisit when data coverage or execution dependencies change.
