## Context

This design delivers the read-only phases 0–4 in the source brief. The accompanying `integration-report.md` records the repository audit, primary-source findings dated 2026-09-18, and baseline of 1,012 passing tests with 3 integration tests deselected. The existing system already supplies FastAPI/Jinja pages, authenticated sessions, SQLAlchemy/SQLite persistence, custom migrations at schema version 16, Kalshi sports research, evidence provenance, lifecycle gates, and paper orchestration. The new work must consume these boundaries without turning a research result into execution authorization.

The main stakeholders are the operator reviewing opportunities, maintainers preserving Kalshi behavior, and future researchers replaying the inputs behind a recommendation. Correct identity, causal timestamps, settlement compatibility, executable prices, and financial units matter more than the number of candidates produced. Existing sports data is insufficient to claim a validated trading strategy; a working scanner will not establish profitability or satisfy future paper-promotion gates.

The report-and-human-response gate from the source brief applies before application implementation. These planning artifacts do not authorize editing `src/`. The confirmed `EmergencyControl.snapshot()` defect remains a separate safety fix with its own timestamp contract, regression tests, commit, and PR. This feature must not absorb that fix or claim it is complete.

## Goals / Non-Goals

**Goals:**

- Introduce venue-neutral research contracts while retaining existing Kalshi identities, data, APIs, and behavior.
- Ingest unauthenticated Polymarket US public data with explicit endpoint capabilities, fee provenance, raw-response auditing, and truthful freshness.
- Produce deterministic, replayable pregame moneyline research from confidently matched, compatible events and at least three distinct current two-sided sportsbook observations.
- Rank zero to five candidates with executable cost, net edge, expected value, confidence, depth, explanations, and isolated advisory stake limits.
- Integrate scan history, watchlists, source health, settings, and manual/opt-in scheduled scans into the existing dashboard and single-node operations model.

**Non-Goals:**

- Polymarket paper fills, positions, settlements, performance ledgers, authenticated balances, credentials, or live orders. Execution-oriented `ProposedTrade`, `Position`, `Settlement`, and `VenueBalance` implementations belong to a later paper change; this release records advisory assumptions explicitly.
- Authenticated combo creation/quotes, probability-product combo pricing, in-play markets, spreads, totals, props, futures, long-dated contracts, or unsupported draw/void structures.
- Purchasing or selecting a paid odds subscription by implication, autonomous AI trade decisions, rewriting the frontend, renaming `kalshi_bot`, or replacing SQLite/migrations as part of this feature.
- Scheduling existing Kalshi capture or paper runners, relaxing existing sports holdout requirements, or claiming research candidates have passed a trading go/no-go gate.

## Decisions

### 1. Add research contracts inside the existing package

Use `domain/prediction.py` for `Venue`, `EventId`, `InstrumentId`, `ContractSide`, `PredictionEvent`, `PredictionMarket`, `MarketQuote`, `OrderBookSnapshot`, `MarketResolutionRule`, `FeeSchedule`, and `ScanCandidate`. Use `data/market_data.py` for the separate read-only `MarketDataAdapter`. Adapters implement sports/leagues/events/markets discovery, market detail, BBO, books, and history where supported. Streaming is an optional declared capability: unsupported operations return an explicit capability result, never fabricated data or a silently empty success.

Canonical identities include venue and external identifier, with internal IDs and explicit alias mappings. A shared real-world event grouping is separate from venue event identity. An identical external string on Kalshi and Polymarket cannot collide; an alias or team-name match cannot merge contracts. Existing `market_ticker` fields retain their Kalshi meaning. `KalshiMarketDataAdapter` wraps the current public client rather than moving parsing into strategies or replacing existing call sites wholesale.

Prices and fees use `Decimal` in USD per contract, with explicit payout, currency, quantity step, tick size, and minimum quantity metadata. Venue-native values remain in raw payloads. Validate the binary $1 payout assumption before ranking. Store exact decimal strings or explicitly scaled integers, not float-derived currency. A quote records side-specific executable bid/ask, source/observed/available/retrieved timestamps, parser version, and raw artifact reference. A book records both prices and quantities. Rules retain full text/source/hash plus normalized outcome, overtime, cancellation, postponement, void, and settlement fields.

Alternative: generalize `BrokerAdapter` now. Rejected because its order/balance responsibility and current integer-cent/ticker assumptions are unnecessary for this read-only path. Alternative: rename the package or reinterpret historical rows. Deferred because neither improves the research boundary and both expand migration risk.

### 2. Keep Polymarket transport and fee rules venue-specific

Use pooled `httpx` transport against `https://gateway.polymarket.us`. `data/polymarket_us/{client,models,adapter,fees}.py` owns documented response validation, endpoint-specific pagination, normalization, and independent Polymarket arithmetic. Public requests carry no trading credentials and cannot target the authenticated trading host. Resolve/document endpoint paths from the official index and recorded fixtures before implementing each operation.

The report's primary-source verification on 2026-09-18 establishes:

| Fact | Design consequence |
|---|---|
| Taker coefficient `0.0695`, effective 2026-09-17; [fee schedule](https://docs.polymarket.us/fees) | Persist schedule coefficient, effective date, source, verification time, and formula version with every scan. |
| Nearest-cent banker's rounding, including documented cumulative taker-fill adjustments; [fee schedule](https://docs.polymarket.us/fees) | Use Decimal half-even and independent known-answer tests; never inherit Kalshi ceiling rounding. |
| Public unauthenticated limit of 20 requests/second/IP; [rate limits](https://docs.polymarket.us/api-reference/rate-limits) | Default below this ceiling, e.g. 5 requests/second, with shared worker limiter and bounded concurrency. |
| League discovery uses `/v2/leagues/{slug}/events`; market/BBO/book/history operations use documented `/v1/...` paths; [league events](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug), [markets](https://docs.polymarket.us/api-reference/markets/get-markets) | Maintain an endpoint capability map rather than a universal API-version prefix. |
| Combo APIs are authenticated beta on `api.polymarket.us`; [combo overview](https://docs.polymarket.us/api-reference/combos/overview) | Display “No combo — authenticated beta research deferred”; do not call these APIs. |

Compute the fee structure as `coefficient × contracts × price × (1 − price)` under the documented rounding scope. Prefer a validated per-market `feeCoefficient`; persist its source and detect invalid, missing, future-effective, or conflicting schedules. An absent coefficient may use a currently verified effective schedule; unresolved material conflicts make the market ineligible. Do not reuse a current coefficient retrospectively for old scans. Multiple book levels require the documented aggregate/cumulative rounding semantics, not repeated single-contract rounding. If an execution-shaped cost cannot be modeled conservatively from public inputs, reject it rather than claim exact executable EV.

Apply connect/read/overall deadlines, bounded exponential backoff with jitter, `Retry-After` support, retry budgets for 429/5xx, reference-data caching, and pagination duplicate/loop guards. Persist sanitized raw payloads and error outcomes, excluding secrets and authenticated headers. Incomplete pagination is a partial scan, not an empty universe. An unsupported endpoint is distinguishable from an outage. Revalidate the external fee/limit/endpoint facts at implementation and record any changed assumption before updating fixtures.

Alternative: a shared Kalshi/Polymarket calculation or guessed global-Polymarket endpoints. Rejected because venue rules and API families differ. Alternative: poll at the published maximum. Rejected because the IP budget can be shared and transient retries need headroom.

### 3. Admit odds sources through a provenance contract

Introduce `OddsProvider` in `data/sports/odds.py`, alongside manual/import and mock implementations. Reuse the existing source allowlist, entitlement record, parser-version, raw-hash, timestamp, and gap-report concepts in `provider_adapter.py`; add canonical mapping types rather than forcing Polymarket IDs into its existing Kalshi fields. A provider response identifies the vendor, original sportsbook, event ID, side/outcome, odds format, market rules, publication/availability/retrieval timestamps, and source artifact.

No vendor becomes active merely because an API key exists. A concrete integration requires recorded league coverage, historical availability, rate limits, terms, retention/attribution, cost, and configured entitlement. The Odds API and OpticOdds remain evaluation options. Retention limits apply to raw and derived artifacts as required by the source terms; after a required deletion, preserve lawful audit metadata and label replay unavailable rather than implying the original inputs remain reproducible.

Manual prices stay visibly labeled, require original source and time evidence, and obey the same eligibility checks. One manually entered estimate cannot count as three books. Test fixtures are never live observations. Duplicate books arriving through multiple vendors count once, using a fixed causal selection rule.

For decimal odds `dA,dB > 1`, derive implied probabilities `uA=1/dA`, `uB=1/dB`, then remove vig using `pA=uA/(uA+uB)` and `pB=1−pA`. Normalize supported American odds before this step. For at least three independently identified valid two-sided books, use the equal-weight mean of their vig-free probabilities for the initial consensus. Persist each contribution, book count, dispersion, selection/exclusion reasons, and algorithm version. Dispersion and temporal inconsistency can reject a candidate; a future weighting scheme requires its own fixed version and validation.

Only snapshots known by the scan decision time are eligible. Availability cannot be later than that decision; old imported snapshots cannot become fresh through a new retrieval time. Configure and freeze quote age, odds age, pair skew, and cross-source skew limits. Proposed initial ceilings are 60 seconds for executable venue quotes/books and 5 minutes for bookmaker prices; empirical latency review may tighten these, and unknown source time fails eligibility. These are conservative operational starting values, not measured feed performance claims.

Alternative: substitute existing evidence-card estimates or LLM probabilities. Rejected because those are not a two-sided sportsbook consensus. Alternative: silently include partial books. Rejected because vig removal and count requirements would no longer be comparable.

### 4. Make matching explicit and rule-aware

`matching.py` first checks shared stable provider identifiers such as `sportradarGameId`. Even a shared ID must pass market and settlement compatibility checks. Fallback matching compares canonical league, participants/aliases, home-away orientation, scheduled start time, event format, and market type. Restrict fuzzy-name use to generating review candidates unless all deterministic identity checks uniquely resolve the fixture under a reviewed mapping rule.

Persist input IDs, normalized names, aliases and versions, candidate alternatives, rule hashes, timestamps, confidence, accepted/rejected/manual-review result, and reason codes. Distinguish high-confidence identity from compatible rules; both are required. Low/ambiguous confidence and conflicting source IDs enter manual review and never receive automatic sizing. A manual mapping is an audited identity decision, not permission to bypass stale data, missing books, rule conflicts, or future changes. Rule or schedule revisions invalidate prior match evidence until rechecked.

Initially rank only binary pregame moneylines whose full settlement semantics are modeled. Soccer with an unmodeled draw, regulation-only versus overtime mismatch, tennis retirement mismatch, or combat draw/no-contest ambiguity is rejected. The configured allowlist includes the brief's major sports, but each league and contract shape needs verified listing, liquidity, and compatible rules before it can produce candidates. Being on the allowlist does not assert coverage.

Alternative: join by normalized team names alone or treat a high fuzzy score as settlement equivalence. Rejected because doubleheaders, reschedules, neutral venues, and rule variants create plausible false joins.

### 5. Freeze each deterministic scan and its advisory allocation

`scanner.py` runs discovery, eligibility screening, executable book acquisition, matching, consensus, fee/slippage calculation, ranking, and advisory allocation. Capture a decision timestamp, configuration hash, code/parser/algorithm versions, input artifact IDs, rule/fee versions, and explicit rejection records. Replays read these frozen inputs and never fetch current data. Freeze deterministic tie-breaking by canonical instrument/side identity after net-edge and quality criteria.

For quantity `q`, executable cost `C` is the depth-supported ask cost plus the documented fee and a nonnegative slippage allowance. With $1 payout and consensus probability `p`, expected net value is `q×p−C`; net edge per contract is `p−C/q`. Gross edge uses the executable ask reference and is displayed separately. Fees and slippage are not subtracted twice. Candidates need at least 0.04 net edge, permitted price 0.60–0.85, sufficient tradable depth, current sources, compatible rules, and a confidently matched event. The 0.70–0.80 preference is only a variance/filter preference; it cannot admit a below-threshold candidate. If policy requires a higher minimum edge outside the preferred band, freeze that threshold in the scan configuration.

Determine maximum acceptable entry price on venue tick increments at the proposed quantity with the same fee rounding, depth, slippage, risk, and minimum-edge constraints. It is a conditional limit based on captured inputs, not a standing order or guarantee of available liquidity. Recompute quantity/cost until the final candidate passes all gates; never size from midpoint, last trade, or a displayed nonexecutable side price.

`data/sports/risk.py` holds a distinct advisory profile: total assumed bankroll $50, initially $50 promotional and $0 withdrawable, daily exposure $20, at most $10 per event, at most three daily positions, and at most $5 for an optional third. Stake means total worst-case cost inclusive of fee/slippage allowance. Normal behavior targets one or two positions, allows zero, and never increases sizing to recover losses. Venue minimum quantity and integer/step constraints can reduce a recommendation to zero. No value changes global/Kalshi bankroll settings or represents a remotely verified account balance or promotional entitlement.

Persist a versioned daily advisory allocation/reservation record scoped to the Polymarket sports profile, account assumption, and fixed risk-day timezone. Use UTC by default, consistent with existing daily-loss semantics; display timezone changes do not reset this day. Positive sized recommendations reserve advisory capacity atomically. Repeat scans for the same event update/reuse its reservation; they do not create new daily capacity. Conservatively retain the day's issued event count and exposure when an opportunity expires or is superseded so later scans cannot repeatedly allocate another $20. Outstanding reservations also count against the $50 total across day boundaries until explicitly reconciled by the operator. Reconciliation records assumptions and does not create fills or settlement/PnL rows. Concurrent scans use the same transaction and cannot overallocate. Any changed reservation policy requires explicit configuration/versioning and tests.

Rank up to five research candidates, but give positive recommended stake only to candidates that fit the aggregate daily/event/bankroll constraints; others display zero stake and the allocation reason. This reconciles five visible candidates with at most three daily positions. Historical results retain their original allocation and timestamps and are never shown as current executable recommendations.

Alternative: independently size each of five rows or reset exposure on every refresh. Rejected because either defeats aggregate limits. Alternative: create a paper ledger to track these assumptions. Deferred because recommendations have no simulated fills, authenticated balance, or realized outcome in phases 0–4.

### 6. Keep runtime AI outside candidate production

No runtime model is required. The deterministic scanner computes probabilities, qualification, order of candidates, risk limits, and stake. Existing Ollama/OpenRouter evidence review may optionally summarize captured evidence, classify conflicts, or mark a deterministic candidate as withheld through an advisory veto. Store that review separately from the immutable deterministic result. It cannot create candidates, invent consensus, change size/edge/risk configuration, grant an exception, or call an execution interface.

If enabled, retain exact provider/model identifier, cited input IDs, prompt/output hashes, timestamps, cost/latency where available, and schema-validation result. Malformed/unavailable output grants no permission and displays “review unavailable.” The scanner remains complete without optional AI; if the operator elects to require advisory review, unresolved review withholds that advisory presentation without silently substituting another model. External content remains evidence, never executable instructions.

Alternative: have an agent rank teams or generate probabilities before deterministic checks. Rejected because it changes the meaning and reproducibility of the consensus strategy. Hosted AI credits are not a prerequisite for this release.

### 7. Add persistence and dashboard workflows without changing their authority

Extend the existing SQLAlchemy models and additive migration mechanism with venue/event/instrument/alias/rule records, raw references, quotes/books, sportsbook snapshots, matching decisions, scan runs, candidate/rejection rows, advisory allocation history, source health, watchlists, and job leases. Scope uniqueness by venue and source; index run/event/instrument/timestamp lookups. Preserve immutable run inputs and output hashes. Persist running/succeeded/partial/failed/interrupted states, counts, and structured errors so zero eligible results are distinguishable from an acquisition failure.

Use new tables or explicit compatibility references rather than rewriting historical Kalshi rows. Do not add paper positions/balances or combo evaluation records merely to make deferred features appear complete. `models.py`, `migrations.py`, settings, and dashboard files are shared integration seams and need staged review against other active work.

Extend existing FastAPI routes/read models/Jinja templates for venue, league, date/timezone, manual refresh, watchlist, candidate detail, rejected reasons/manual review, risk assumptions, history, and source health. Manual imports must remain visibly distinct. Refresh while a page is open only polls durable state; closing the browser does not terminate a scan. Show last successful refresh, input ages, partial-source failures, unavailable feeds, and stale candidates; never derive “Live” from page availability. Unsupported paper/combo capabilities have explicit unavailable text and no functional execution controls.

Every scanner route uses existing session authentication. Mutation endpoints for refresh, settings, imports, watchlist, matching review, or advisory reconciliation preserve CSRF/origin defenses. Imported identifiers/text are validated and escaped. Provider keys remain in server-side `Settings`, never response bodies, exports, raw URL logs, or client JavaScript. Regenerate `.env.example` through its existing generator when implementing settings.

Emergency state comes from existing durable governance, with the separately fixed snapshot contract where applicable. Scanner stop means stop ingestion/recommendation work; it does not liquidate anything or stop unrelated workers. A global halt may allow read-only collection but suppresses new positive advisory allocations and reports the reason. No scanner route resumes global execution or implies that an advisory budget enforces an external account's spending.

Alternative: a separate SPA or separate authentication scheme. Rejected because current FastAPI/Jinja and shared session controls support the requirement and avoid divergent operational truth.

### 8. Deploy one always-on node with scanner-specific scheduling

Use `uv run python scripts/scan_polymarket_sports.py` following repository script conventions, with manual one-shot and explicit service/schedule modes. Scheduling is opt-in and scoped solely to the public scanner. Morning, pregame, and periodic refresh schedules use configured timezone with tested DST behavior and bounded catch-up; missed runs do not become a burst of stale recommendations.

Manual and scheduled triggers share a durable job key and SQLite-backed lease/heartbeat with ownership/fencing semantics. A expired/reclaimed lease cannot let the previous worker publish or allocate. Mark interrupted runs and persist retry reasons. Use short transactions, bounded batches, bounded network concurrency, and single scanner ownership; do not hold database transactions across HTTP calls. Dashboard auto-refresh does not spawn independent data pollers. Completion, failure, shutdown, and restart must leave observable job state.

Recommended deployment is the existing FastAPI app and a scanner process on one always-on Windows/home-server machine with persistent local SQLite, accessed over a private encrypted mesh/tunnel or authenticated TLS reverse proxy. Document Windows Task Scheduler/service startup, working directory, dedicated least-privilege account, logs, restart/stop behavior, backups, rotation, and clock synchronization. Avoid storing the live database in a concurrently synchronized/network-share folder.

Preserve launcher's existing non-loopback secret and TLS requirements. Direct remote binding uses certificate/key and authenticated sessions. A loopback-bound reverse-proxy setup requires explicit trusted-proxy/origin configuration, secure-cookie handling for the external HTTPS origin, and disabling exposure of local bootstrap conveniences to remote clients; a private tunnel does not replace application authentication. Verify the actual chosen topology before exposing a route.

Vercel is not the primary host: the report documents bounded Python function execution and ephemeral storage incompatible with the current local SQLite and durable-worker model. A future Vercel-facing split requires managed persistence, a durable external worker/queue, distributed locking, and separate deployment review. An always-on container with managed Postgres is also a later option, not a required migration for remote access.

Alternative: a scheduler tied to browser activity. Rejected because scans must survive a closed dashboard. Alternative: schedule every existing collector/paper runner. Rejected because their foreground-only contracts remain owned by other changes.

### 9. Reconcile open-change ownership before touching shared seams

| Existing change | Reused contract and boundary |
|---|---|
| `sports-market-feasibility` | Reuse causal capture/rules, realistic costs, chronological holdout and promote-or-park evidence. Its Kalshi collector remains foreground-only. Scanner output is research and does not replace missing captured validation data. |
| `sports-evidence-and-flow-research` | Reuse source entitlements, timestamps/hashes, allowlists, and advisory-only LLM review. Evidence/flow features never count as sportsbook consensus or relax identity/rules gates. |
| `multi-venue-paper-trading` | Retains ownership of execution contracts, domain ledgers, promotion, and foreground paper orchestration. Consume durable halt/lifecycle state without adding Polymarket paper admission or scheduler authority to that runner. |
| `trader-dashboard-experience` | Retains shared authentication, CSRF/origin, visual shell, truthful control/state and accessible partial/error states. Add scanner views/read models under those contracts, reconcile route/schema edits before implementation. |
| Separate `EmergencyControl` fix | Owns calling `allows_new_entries` with a sound timestamp and daily-loss-only/no-panel regression coverage. Require evidence of its completion before relying on snapshot status; do not implement it in this feature. |

At implementation start, re-read the current tasks/design/reconciliation artifacts for these changes; task counts in the report are a dated snapshot. Record shared-file ownership and remaining prerequisites in this change's tasks. No living capability specs exist at planning time, so create this change's five new capabilities rather than claiming modifications to nonexistent main specs. Subsequent spec archival/sync must reconcile any capabilities introduced in the meantime.

## Risks / Trade-offs

- [False identity or settlement equivalence] → Require stable IDs or reviewed deterministic matching, versioned rules, explicit ambiguity rejection, and traceable manual decisions.
- [Apparent edge disappears under costs or stale data] → Exact Decimal arithmetic, quantity/depth-aware fees, conservative slippage, time/skew gates, maximum-price tests, and no midpoint fallback.
- [Provider entitlement or history is insufficient] → Default to labeled fixtures/manual research, block unadmitted data, retain coverage gaps, and avoid claiming empirical validation from a technical demo.
- [Fee/API documentation changes after planning] → Reverify at implementation, retain effective versions with scans, reject unresolved schedules and unsupported payload changes.
- [Repeated scans multiply an advisory budget] → Atomic durable reservations, stable day/event identity, fenced worker publication, and no implicit capacity reset on expiration.
- [Advisory exposure differs from actual external holdings] → Label all balances/reservations as assumptions and require explicit operator reconciliation; do not claim execution enforcement.
- [SQLite growth/contention and raw retention limits] → Short writes, indexed bounded queries, raw retention policy compatible with source terms, backups, and truthful replay availability.
- [Remote dashboard overstates safety or leaks secrets] → Existing auth/CSRF/origin contracts, encrypted transport, separate snapshot fix, sanitized payloads, and verified controls with accurately stated scope.
- [Scope conflicts across open changes] → Preserve ownership table, recheck dependencies before shared-file edits, and keep paper/combo/live work in later changes.
- [LLM behavior contaminates reproducible outputs] → Separate optional review storage and immutable deterministic calculations; grant models no sizing, probability, configuration, or execution authority.

## Migration Plan

1. Complete and validate phase-0 planning, record the human response required by the brief, reconcile active changes, and complete the separately owned emergency snapshot fix with its own tests/commit/PR. Keep application implementation gated until these prerequisites are satisfied.
2. Back up a representative SQLite database with all writers stopped or using a consistent SQLite backup; record the schema version and a restore check. Recheck current migration head to avoid colliding with another change's version assignment.
3. Add canonical types, Kalshi wrapper, and independent fee implementations first. Confirm unchanged Kalshi behavior before introducing Polymarket routes or scheduler configuration.
4. Add new tables/indexes through the existing migration mechanism and tested fresh/upgrade paths. Do not reinterpret or bulk rewrite old ticker rows. New settings default to disabled ingestion/scheduling and no concrete odds provider; regenerate `.env.example`.
5. Run mocked/manual ingestion and replay checks, then opt-in public endpoint smoke tests with no credentials. Enable one-shot observation locally; source failures produce explicit failed/partial runs and no newly eligible allocations.
6. Enable deterministic consensus/ranking with admitted provider inputs and advisory limits. Review actual data freshness, mapping, rule compatibility, rejection reasons, and repeat-scan reservation behavior before scheduling.
7. Enable dashboard views locally, validate authenticated mutation/read paths, then enable scanner-only scheduling on one node. Exercise restart/lease recovery, backup/restore, browser-closed operation, and the chosen private remote-access topology before declaring phase 4 complete.

Rollback disables the scanner/scheduler, stops the scanner worker, and reverts feature code/config while retaining additive data for inspection. Do not drop new tables or lower migration versions as an automatic rollback. Verify the prior application tolerates the additive schema; if it does not, restore the validated pre-upgrade backup during a stopped-writer maintenance window and explicitly account for post-backup observations. Legacy Kalshi reads and processes must remain functional throughout the supported upgrade/rollback path.

## Entry and Exit Gates

| Phase | Entry gate | Exit evidence |
|---|---|---|
| 0: planning | Source brief/repo/report inspected; no application changes | Complete proposal/design/five specs/tasks; OpenSpec validation; dated baseline and primary-source facts; overlap ownership; report delivered and human response recorded before implementation. Separate emergency fix remains separately owned and must complete before phase 1 implementation. |
| 1: research contracts | Phase-0 implementation gate and separate safety-fix prerequisite satisfied | Canonical identity/units, adapter capabilities and independent fee tests pass; existing Kalshi regressions stay green; no broker/order path added. |
| 2: public ingestion | Phase-1 contracts accepted | Mocked pagination/retry/schema/fee/time cases pass; raw/provenance/storage upgrade evidence exists; opt-in unauthenticated endpoint smoke results recorded; unavailable capabilities and missing liquidity fail closed. |
| 3: deterministic scanner | Phase-2 data usable; admitted odds inputs and frozen matching/risk policy | Three-book two-sided causal consensus; compatible high-confidence matches; executable net costs; zero-to-five deterministic replay; daily/event/total limits and concurrent/refresh tests pass. Missing provider evidence yields an explicit research-only/no-candidate result. |
| 4: operations | Phase-3 evidence and shared dashboard/security contracts satisfied | Authenticated views/mutations, truthful stale/partial/halt state, browser-closed scans, restart/lease/idempotency, backup/rollback and private remote-access checks pass; docs and `.env.example` synchronize; full default suite passes. |

Finishing phase 4 authorizes no paper or live execution. A later paper proposal requires sufficient causal captures, predeclared chronological holdout and execution-realistic evidence, its own acceptance thresholds, and separate authorization. Authenticated combo research and live trading each require separate scope and approval.

## Test Plan

- **Identity and compatibility:** Same external ID on two venues, alias collision, Kalshi round-trip wrapper behavior, units/ticks/quantity validation, immutable rule revisions, and unknown capabilities.
- **Fees and valuation:** Official known-answer examples, half-even boundaries, multiple quantities/levels and cumulative rounding, per-market/fallback/effective-date selection, stale/conflicting schedule rejection, fee/slippage inclusion exactly once, exact threshold boundaries, and maximum-entry-price search. Preserve current Kalshi ceiling-fee tests unchanged.
- **Public transport:** Recorded/mocked nested v2 league and v1 market payloads; empty and paginated results; duplicate-page protection; malformed/missing side/quote/quantity; 429/Retry-After, bounded 5xx/timeouts, exhausted retries, stale books, raw hashes, and unsupported endpoints. Assert public ingestion has no authenticated host/credential/order route. Network tests remain separately marked and excluded by default.
- **Odds and matching:** American/decimal conversion, vig removal and mean consensus, three distinct books versus duplicates, one-sided books, skew/future availability/stale imports, invalid entitlement, stable-ID disagreement, doubleheaders/reschedules, neutral/home-away cases, rule mismatches, draw/retirement/no-contest exclusions, and invalidated manual mappings.
- **Scanner and risk:** Complete zero-candidate success versus partial/failed acquisition; deterministic replay and tie order; five ranked rows with at most three positively sized daily events; $50/$20/$10/$5 boundaries; minimum quantity/depth; repeated and concurrent scans; UTC day rollover versus display timezone; outstanding cross-day reservations; operator reconciliation audit; global halt suppression; AI absent/malformed/veto without altering deterministic probability/stake.
- **Storage and operations:** Fresh DB and representative schema-v16 upgrade, idempotent rerun, uniqueness/indexes, unchanged legacy reads, atomic run/reservation publication, interrupted transactions, fenced stale workers, duplicate schedule delivery, crash/restart recovery, bounded missed-run catch-up, DST, disk/write failure, and consistent backup/restore.
- **Dashboard/security:** Unauthenticated reads and mutations denied, CSRF/origin protection, escaped provider text, no secret exposure, expired data/partial source health, manual-data labeling, historical versus current outputs, unavailable combo/paper status, accurate halt scope, remote cookie/TLS/proxy behavior, and browser-closed worker continuity.

Use the existing unit/backtest/integration conventions and `uv run pytest` for the final default regression suite; the report's 1,012 passing baseline is comparison evidence, not a guarantee for future commits. Required targeted tests accompany each bounded slice. Regenerate and check `.env.example` only during implementation, run relevant lint/type/docs checks defined by the repository, and avoid live network dependencies in default CI. Planning validation checks artifacts and does not claim any of these implementation tests have been written or run.

## Open Questions

| Question | Recommended default / resolution gate |
|---|---|
| Which concrete sportsbook provider and entitlement? | Manual/mock contracts first; record The Odds API/OpticOdds coverage, retention, history, cost and source approval before enabling a concrete vendor. No subscription purchase is implied. |
| Which initial league/rule variants have reliable binary coverage? | Admit per fixture/rule evidence; omit ambiguous draws, overtime/retirement/void cases. Verify actual available markets in phase 2 rather than assuming the full allowlist is rankable. |
| What source freshness, skew, start-time horizon and slippage bounds fit actual feeds? | Freeze conservative settings before phase-3 acceptance; start with 60-second quote/book and 5-minute odds ceilings, same selected local event day and strictly pregame status. Tighten after measured latency/depth review; never tune on held-out outcomes. |
| How should operator advisory reconciliation affect outstanding capacity? | Retain issued daily counts/exposure conservatively; release only outstanding cross-day reservation through audited explicit reconciliation. Do not infer execution or settlement. Confirm this workflow in phase-3 review. |
| Which private deployment topology will the operator use? | One always-on node/private access first. Verify certificate, auth, trusted origin/proxy and secure-cookie behavior on that topology before phase-4 remote rollout. |
| What retention is lawful and practical for provider/raw scans? | Preserve enough for reproducible evaluation within entitlement terms; disclose gaps or removed raw data explicitly. Set per-source retention before admitting data. |
| When can this become paper trading? | Only a separately scoped paper change after causal data and predeclared validation gates; no date or positive strategy conclusion is implied by scanner completion. |

## Model Complexity and Allocation

Complexity is high because identity/rules, financial arithmetic, causal inputs, migration compatibility, concurrency, remote security, and shared safety contracts interact. Use GPT-6 Astra or Claude Opus 5 for architecture, requirements, fee/risk/identity and security decisions, task decomposition, and final integration acceptance. Use GPT-5.6 Sol/Terra or Claude Sonnet 5 for bounded implementation after contracts stabilize. Use GPT-5.6 Luna or Claude Haiku 4.5 for mechanical fixtures, mappings, repetitive documentation, and formatting, with architecture-class review for anything touching money or authority.

These are development allocations, separate from the optional runtime AI boundary. Verify actual model/account availability before assigning work; mentioning an Anthropic option does not assert that it was executed. Preserve written contracts/checkpoints when switching. Escalate uncertainty in currency/rounding, identity/settlement, risk or ledger authority, schema/security, conflicting open changes, or two unsuccessful attempts at the same acceptance scenario. Never weaken tests or admission criteria to fit a cheaper model.

## Checkpoint

Design artifact complete for planning phases 0–4. Inputs were the source brief, current proposal/integration report, CLI `openspec instructions design --change polymarket-us-and-sports-scanner --json`, related proposals, and inspected migration/provider/emergency-control/launcher code. This artifact makes no application changes and claims no implementation-test completion. Current dated baseline and external facts remain those recorded in the integration report.

Resume with `openspec status --change polymarket-us-and-sports-scanner --json`; preserve completed artifacts and read the next CLI instructions for specs/tasks. Reconcile all five capability specs and task gates with this design, validate the full change, and deliver the report/planning package. Record the brief-required human response before source implementation. Track the separate emergency fix by its own change/commit/PR evidence. Before implementation, recheck active-change ownership, current schema version, provider admission and current Polymarket fee/API documentation. The model allocation and escalation triggers above apply to the next handoff; no paid provider, hosted AI, paper trading, combo credentials or live execution is authorized by this checkpoint.
