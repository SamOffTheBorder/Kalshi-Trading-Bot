## ADDED Requirements

### Requirement: Planning and implementation entry gates
Implementation SHALL begin only after the integration report exists, the human has replied to it as required by the source brief, and proposal, design, capability specs, tasks, migration/test plans, and explicit phase gates are complete. The confirmed `EmergencyControl.snapshot()` defect SHALL be resolved with a timestamp-aware regression test in its own change, commit, and PR before scanner implementation relies on it; this feature MUST NOT absorb that fix. Phase entry decisions SHALL reconcile overlapping sports research, paper, and dashboard changes and preserve their existing foreground-only and promotion contracts outside this scanner.

#### Scenario: Planning is complete but report response is absent
- **WHEN** the next action would modify application code
- **THEN** implementation remains paused at the report-response gate with the exact prerequisite recorded

#### Scenario: Emergency snapshot regression is not independently resolved
- **WHEN** scanner implementation is considered ready to start
- **THEN** the separate safety-fix dependency remains an explicit unmet entry gate rather than being silently bundled into the feature

### Requirement: Additive auditable storage migration
The system SHALL extend the existing versioned additive SQLite migration mechanism for venue identities, events/markets/aliases/rules, quote/book/odds snapshots, match and review decisions, scan runs, ranked and rejected candidates, advisory allocations, source health, and audit references. Migrations SHALL be idempotent, preserve existing Kalshi rows and queries, maintain referential integrity, and be tested on a populated current database and a clean database. The migration plan SHALL specify backup, verification, interrupted-run recovery, and application rollback limits. It MUST NOT silently introduce Alembic, reinterpret historical rows, or create Polymarket paper positions or authenticated balances in this phase.

#### Scenario: Migration runs twice against populated storage
- **WHEN** the additive migration is reapplied after initial success
- **THEN** schema and data remain valid without duplicate records or changed meanings for legacy Kalshi rows

#### Scenario: Migration is interrupted
- **WHEN** a process stops before migration completion
- **THEN** recovery follows the documented transaction/version procedure and an unverified database is not advertised as ready

### Requirement: Durable replayable scan lifecycle
Each scan SHALL persist its request filters, local date/timezone and UTC cutoff, algorithm/config versions, fee and risk snapshots, raw input references/hashes, coverage, matching decisions, candidates, exclusions, allocation version, timings, and error/health state. States SHALL distinguish running, completed with zero or more candidates, partial, failed, interrupted, and duplicate/skipped invocations. Publishing candidates and their associated allocation SHALL be atomic. Historical records SHALL remain attributable to the original inputs even after rules, settings, or sources change.

#### Scenario: Process stops before publication
- **WHEN** a worker crashes after capturing inputs but before the final transaction
- **THEN** the scan remains interrupted or recoverable and no partial candidate set appears as a completed allocation

#### Scenario: Historical scan is inspected after configuration changes
- **WHEN** the operator opens an old scan
- **THEN** the dashboard displays its frozen settings, inputs, costs, and reasons rather than recalculating it using today's configuration

### Requirement: Integrated truthful dashboard workflow
The scanner SHALL extend the existing authenticated FastAPI/Jinja dashboard with venue, sport/league, date/timezone filters; manual refresh; refresh while running; candidates and details; watchlist; rejections/manual review; advisory risk assumptions; history; settings; source health; last successful refresh; and stale/partial/error states. Manual price/odds inputs SHALL be visibly labeled fallback data and remain subject to qualification gates. `Live` SHALL describe data only when the requisite source connections and freshness are actually healthy and MUST NOT imply live trading. Paper results and combo capabilities SHALL be visibly unavailable/deferred for Polymarket, with `No combo` as the default, rather than fabricated.

#### Scenario: Page loads successfully while source data is stale
- **WHEN** the latest quote or odds source exceeds its freshness budget
- **THEN** the page shows stale/degraded status and timestamps and does not label the data healthy or live because the HTTP page request succeeded

#### Scenario: Completed scan has zero candidates
- **WHEN** the user opens a successful empty scan
- **THEN** the page identifies zero qualifying opportunities and exposes rejection reasons without depicting an error or urging a trade

### Requirement: Truthful emergency-control status
Scanner views SHALL show durable emergency-control scope, state, reason, and observation time using the existing shared governance contract and separately corrected snapshot behavior. Read-only collection and funded advisory recommendations SHALL be distinguished: a shared halt SHALL suppress positive actionable stake recommendations while preserving permitted read-only collection and explicit halt evidence. Unknown guard state SHALL fail closed for positive stake allocation. Controls SHALL claim only effects actually enforced and MUST NOT advertise Polymarket order cancellation or position closure.

#### Scenario: Global halt is active during scanning
- **WHEN** fresh public data yields qualifying research opportunities
- **THEN** research results can be retained but positive stake recommendations are blocked with the halt reason visible

#### Scenario: Guard state cannot be obtained
- **WHEN** the dashboard or scanner cannot read the required safety state
- **THEN** it displays unknown/degraded state and no positive actionable stake is published

### Requirement: Browser-independent opt-in scanner scheduling
The system SHALL provide a manual scanner CLI following the existing `uv run python scripts/<name>.py` convention and opt-in scheduled morning, pregame, and periodic refresh execution. Schedules SHALL specify timezone, handle daylight-saving transitions, stop refreshing started events, and continue with the browser closed while the service is running. Installing or opening the dashboard SHALL not silently start a scheduler. New unattended authority SHALL apply only to this read-only scanner; existing collectors and paper runners SHALL retain their foreground-only requirements.

#### Scenario: Browser closes during a scheduled service run
- **WHEN** an enabled schedule becomes due while no dashboard client is connected
- **THEN** the server-side scanner executes and persists its result independently of browser polling

#### Scenario: Dashboard starts with scheduler disabled
- **WHEN** the user launches the existing dashboard
- **THEN** no unattended scanner or existing paper/collector process starts implicitly

### Requirement: Idempotent concurrency and worker recovery
Scheduled invocations SHALL use stable schedule/slot/filter identities and durable uniqueness/locking to prevent duplicate successful runs or duplicate advisory allocations for the same invocation. Manual refreshes SHALL follow an explicit coalescing or serialization policy. Locks SHALL have bounded recovery with owner/heartbeat evidence; recovery MUST NOT admit concurrent owners. The supported SQLite deployment SHALL bound writers and surface contention and missed jobs. Scheduler failures SHALL be visible and MUST NOT erase the last successful scan or turn stale output into current output.

#### Scenario: Scheduler delivers the same invocation twice
- **WHEN** two workers receive an identical schedule slot key
- **THEN** at most one publishes a successful run and allocation and the other records a duplicate/skipped result

#### Scenario: Worker dies while holding a lock
- **WHEN** its heartbeat expires and recovery verifies the old ownership is invalid
- **THEN** a new worker can claim the invocation without concurrent publication or duplicated advisory exposure

### Requirement: Authenticated encrypted remote operations
Every scanner page, data route, export, and mutation SHALL retain the existing dashboard session authentication. Mutations, including scan requests, review actions, watchlist/settings changes, and controls, SHALL retain CSRF/origin protection and audit attribution. Remote access SHALL require encrypted transport and configured authentication; unauthenticated non-loopback exposure SHALL fail closed. Session cookies and provider secrets SHALL retain existing secure handling. Documentation SHALL cover a single always-on Windows/home-server host, private tunnel/mesh or correctly configured authenticated reverse proxy, least-privilege service operation, secret rotation, backup/restore, startup/shutdown, and recovery.

#### Scenario: Unauthenticated remote client requests scan history
- **WHEN** a request lacks a valid dashboard session
- **THEN** the server denies scanner data access rather than exposing a read-only authentication bypass

#### Scenario: Cross-origin request tries to trigger a scan
- **WHEN** a mutation fails CSRF or origin validation
- **THEN** it is rejected before starting a job or altering review, allocation, or settings state

#### Scenario: Non-loopback startup lacks secure configuration
- **WHEN** the server is configured for remote binding without required authentication or encrypted transport
- **THEN** startup refuses the unsafe configuration and reports the missing prerequisite

### Requirement: Persistent-host deployment and Vercel compatibility boundary
The primary release SHALL run the existing dashboard and scanner on an always-on host with persistent storage and documented single-node locking assumptions. Vercel SHALL remain optional and outside the primary worker/database path. Documentation MUST NOT claim that browser polling, ephemeral function-local SQLite, or bounded serverless requests provide durable background execution. Any future Vercel-hosted dashboard/API compatibility SHALL require explicit persistent external storage, durable worker/queue ownership, authentication, distributed idempotency, and deployment validation before being advertised as supported.

#### Scenario: Operator considers deploying the entire stack to Vercel
- **WHEN** deployment planning detects local SQLite and a long-running scanner requirement
- **THEN** documentation identifies the incompatibility and directs the supported deployment to persistent hosting without claiming serverless persistence

### Requirement: Authoritative settings and observable operations
All new client, provider, scanner, freshness, fee-policy, risk, schedule, and deployment settings SHALL be defined through the existing `Settings` source of truth and regenerated `.env.example` workflow. Validation SHALL reject negative cost allowances, invalid timezones, contradictory budgets, invalid freshness/rate bounds, and unsupported capabilities. Health reporting SHALL distinguish reachability, coverage, freshness, last success, last error, and scheduler/lock state. Logs and exports SHALL preserve useful audit IDs while redacting secrets.

#### Scenario: Generated settings example drifts
- **WHEN** a scanner setting is added without regenerating the example
- **THEN** the existing configuration drift check fails until the generated example matches authoritative settings

### Requirement: Phased acceptance and resumable model review
Phase 4 acceptance SHALL require clean and populated migration tests; complete and partial/zero scan persistence/replay; browser-closed scheduling; duplicate delivery, concurrency and restart tests; dashboard stale/empty/error/history truthfulness; authentication/CSRF/remote-startup rejection tests; settings drift checks; and existing Kalshi regressions. Public network tests SHALL remain opt-in. Recorded live smoke evidence SHALL identify gaps rather than fabricate provider coverage. The change checkpoint SHALL retain stage, completed artifacts, next action, unresolved decisions, verification status, selected model, and escalation triggers. High-complexity architecture/security/financial acceptance SHALL use the proposal's GPT-6 Astra allocation or an availability-verified architecture-class alternative; bounded Sol/Terra/Claude Sonnet work and mechanical Luna work SHALL not lower acceptance criteria. Runtime hosted AI SHALL remain opt-in, evaluated, budget-capped, and independent of subscription entitlements.

#### Scenario: Replacement model resumes the work
- **WHEN** the active model changes or reaches a limit
- **THEN** the replacement reads OpenSpec status, instructions, and completed context and continues from the recorded checkpoint without regenerating completed artifacts

#### Scenario: Read-only release acceptance succeeds
- **WHEN** phases 0-4 meet their recorded entry and exit criteria
- **THEN** release evidence identifies only the read-only capabilities delivered and retains separate paper, combo, authenticated trading, and live go/no-go gates
