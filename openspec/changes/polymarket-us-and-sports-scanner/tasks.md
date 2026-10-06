## 1. Phase 0 prerequisites and ownership

- [x] 1.1 Record delivery of `integration-report.md` and the human's response required by the source brief; do not edit application code before that response is recorded. (2026-09-18: operator issued `$openspec-apply-change polymarket-us-and-sports-scanner`, authorizing this change to begin subject to its remaining entry gates.)
- [x] 1.2 Verify the separate `EmergencyControl.snapshot()` safety change has a timestamp-aware daily-loss-only/no-panel regression test and independent commit/PR evidence; record it as a prerequisite without implementing or absorbing its fix here. (2026-09-23: independent `fix-emergency-control-snapshot` change and commit `3ebf662`; snapshot now requires `ts`, delegates to the admission predicate, and has daily-loss-only/no-panel, rollover, and panel-sticky regression coverage. Focused tests: 15 passed; default suite: 1,015 passed, 3 deselected.)
- [x] 1.3 Re-read current design/tasks/reconciliation artifacts for `sports-market-feasibility`, `sports-evidence-and-flow-research`, `multi-venue-paper-trading`, and `trader-dashboard-experience`; record shared-file ownership and unresolved dependencies. (2026-09-18: feasibility/evidence remain foreground research with no sufficient sports captures; multi-venue retains paper ledgers, global governance, and foreground runner ownership; dashboard experience retains session auth, CSRF/origin and shared UI contracts. Scanner may add read-only modules/views only after reconciling shared storage/settings/web seams. No ownership conflict is resolved by this change.)
- [x] 1.4 Confirm proposal, design, all five capability specs, migration/test plans, and phase gates are complete; run `openspec validate polymarket-us-and-sports-scanner --strict` and retain the result. (2026-09-18: strict validation passed.)
- [x] 1.5 Record phase-0 exit and phase-1 entry evidence, including the dated 1,012-pass/3-deselected baseline, human response, independent safety fix, and preserved paper/foreground-runner boundaries. (2026-09-23: human apply authorization recorded in 1.1; independent safety commit `3ebf662` verified; current regression baseline is 1,015 passed/3 deselected; paper, combo, authenticated trading, and existing foreground-runner boundaries remain outside this change.)

## 2. Model allocation and resumable working checkpoint

- [x] 2.1 Record high-complexity ownership for GPT-6 Astra or availability-verified Claude Opus 5: architecture, financial/identity/security decisions, migration review, and final acceptance. (2026-09-18: GPT-6 Astra reserved in `implementation-checkpoint.md`; no claim that an unavailable alternative performed work.)
- [x] 2.2 Assign bounded implementation to GPT-5.6 Sol/Terra or availability-verified Claude Sonnet 5 and mechanical fixtures/docs to GPT-5.6 Luna or Claude Haiku 4.5 under fixed contracts; record actual availability without claiming unused models executed work. (2026-09-23: GPT-5.6 Sol assigned bounded Phase-1 domain contracts/tasks 3.1–3.4; GPT-6 Astra remains the architecture/financial/identity acceptance reviewer. No Anthropic execution is claimed.)
- [x] 2.3 Create the implementation checkpoint with stage, completed artifacts/tasks, next action, unresolved decisions, verification evidence, active model, and authoritative `openspec status --change polymarket-us-and-sports-scanner --json` command. (2026-09-18: see `implementation-checkpoint.md`.)
- [x] 2.4 Record escalation triggers for uncertain units/rounding, identity/rules, risk/ledger authority, migration/security, cross-change conflicts, or two failed attempts; require architecture-class review without weakening acceptance criteria. (2026-09-18: recorded in `implementation-checkpoint.md`.)

## 3. Phase 1 canonical domain and adapters

- [x] 3.1 Add venue/event/instrument/side identity contracts with venue-scoped external IDs, explicit canonical IDs, aliases, and a separate real-world event grouping; test equal external IDs across venues and alias collisions. (2026-09-23: `domain/prediction.py` provides frozen venue-scoped identities and separate real-world grouping; focused tests cover equal external IDs on Kalshi/Polymarket US.)
- [x] 3.2 Add event/market/resolution-rule contracts preserving participants, orientation, sport/league, lifecycle times/status, settlement text/source/hash, and immutable raw provenance. (2026-09-23: frozen event, market, rule, and raw-reference contracts added; missing orientation prevents rankability.)
- [x] 3.3 Add Decimal quote/book contracts with explicit currency, payout, tick/quantity step, minimum quantity, side-specific executable prices/depth, and source/observed/available/retrieved timestamps; test precision and causal round trips. (2026-09-23: Decimal-only quote/book contracts preserve precision and enforce timezone-aware causal timestamps; 3 focused tests plus Ruff/Pyright pass.)
- [x] 3.4 Add research fee/candidate contracts and explicit unsupported/missing-field statuses; verify incomplete side or settlement metadata cannot qualify a market. (2026-09-23: frozen Decimal fee/fill/estimate, candidate, assessment, and incomplete raw-market contracts added; focused tests: 7 passed; Ruff/Pyright pass.)
- [x] 3.5 Define the read-only `MarketDataAdapter` protocol for discovery, detail, BBO, books, history, and capability-declared streaming; verify it exposes no broker, order, authenticated balance, or wallet operation. (2026-09-23: `data/market_data.py` provides a runtime-checkable read-only protocol, declared capabilities, and typed unsupported results. Focused tests: 3 passed; Ruff/Pyright pass.)
- [ ] 3.6 Implement `KalshiMarketDataAdapter` as a compatibility wrapper over existing public clients; test equivalent identifiers/values and explicit unsupported-capability behavior without moving payload parsing into strategies.
- [ ] 3.7 Run domain/adapter and existing Kalshi regression tests; verify package imports, commands, historical ticker meaning, global risk defaults, and execution interfaces remain unchanged.

## 4. Phase 1 independent fee semantics

- [x] 4.1 Reverify Polymarket US fee, rate-limit, endpoint, and combo primary documentation; record verification dates and any changes to the report's 0.0695 coefficient effective 2026-09-17, half-even rounding, 20 requests/second/IP, mixed v1/v2 paths, and authenticated-beta combo findings. (2026-09-23: primary fee/rate-limit/sports docs reconfirm 0.0695 effective 2026-09-17; half-even cent rounding with cumulative multi-fill adjustment; public 20 req/s/IP; v2 sports and v1 market paths. Combo work remains authenticated/deferred; no contrary fact found.)
- [ ] 4.2 Add the fee interface with venue, coefficient, effective date, source, formula/rounding version, quantity/price, and aggregation scope; preserve the existing Kalshi calculation through a compatibility implementation.
- [ ] 4.3 Implement separate Decimal Polymarket `coefficient × contracts × price × (1 − price)` arithmetic with documented half-even cent and cumulative taker-fill adjustments.
- [ ] 4.4 Implement applicable per-market coefficient precedence, verified effective-default fallback, frozen historical schedule selection, and rejection of unresolved invalid/conflicting/inapplicable fee semantics.
- [ ] 4.5 Add official known-answer and exact half-cent/multi-fill/multi-level/effective-date fixtures; verify historical replay and unchanged Kalshi ceiling rounding.
- [ ] 4.6 Record phase-1 exit and phase-2 entry evidence from identity/unit/adapter/fee and Kalshi regressions, with architecture review of financial semantics and confirmation that no execution path was added.

## 5. Phase 2 storage and authoritative settings

- [ ] 5.1 Recheck the current schema head against other active changes; document the additive migration version and verify a consistent representative SQLite backup/restore before upgrading populated storage.
- [ ] 5.2 Add venue/event/instrument/alias/rule/raw-reference tables with venue-scoped uniqueness and immutable provenance; preserve existing Kalshi rows and queries.
- [ ] 5.3 Add quote/book/odds snapshot and match/review tables with exact monetary storage, source timestamps, audit references, foreign keys, and bounded-query indexes.
- [ ] 5.4 Add scan/candidate/rejection/health/watchlist tables with frozen input/config/version references and explicit running/completed/partial/failed/interrupted/duplicate states.
- [ ] 5.5 Add advisory day/event reservation, commitment/reconciliation audit, and job lease/heartbeat/version tables; keep these distinct from paper positions, fills, settlements, or authenticated balances.
- [ ] 5.6 Extend the existing SQLite migration mechanism and test fresh creation, populated current-schema upgrade, repeated application, interrupted recovery, referential integrity, and unchanged legacy reads; do not introduce Alembic.
- [ ] 5.7 Add client/provider/freshness/risk/allowlist/schedule/deployment settings through `Settings`, defaulting scheduling and commercial providers off with no Polymarket credentials.
- [ ] 5.8 Validate budgets, nonnegative costs, timezones, freshness/skew/rate bounds, tick/quantity constraints, and capability choices; test invalid and contradictory configurations fail clearly.
- [ ] 5.9 Regenerate `.env.example` using `scripts/generate_env_example.py`, run the drift check, and verify provider secrets are excluded from serialization/logging/export paths.

## 6. Phase 2 Polymarket public transport and ingestion

- [ ] 6.1 Create a verified gateway endpoint/capability map from official documentation, including v2 league events and documented v1 market/BBO/book/history operations; explicitly reject authenticated trading/combo operations.
- [ ] 6.2 Implement pooled transport with connect/read/overall deadlines and shared single-node rate/concurrency budgets below the verified public limit; test simultaneous jobs and retries share the budget.
- [ ] 6.3 Implement bounded 429/Retry-After, 5xx and timeout retry/backoff with structured permanent-error handling; test exhaustion terminates and degrades source health.
- [ ] 6.4 Implement endpoint-specific pagination, stable-ID deduplication, repeated-page protection, page/time bounds, and partial/truncated status; test later-page failures preserve auditable partial results.
- [ ] 6.5 Validate nested events/markets/sides, participant/shared IDs, state flags, market types, tradability, minimum quantity, fee coefficient, and numeric/timestamp shapes; retain malformed raw inputs and errors.
- [ ] 6.6 Implement `PolymarketUSMarketDataAdapter` normalization for supported sports/leagues/events/markets/detail/BBO/books/history, preserving unsupported and absent-league statuses.
- [ ] 6.7 Add explicit reference-data TTL caching and independent executable quote/book freshness checks; test cached reads never refresh source time and indicative prices never substitute for executable asks.
- [ ] 6.8 Persist sanitized endpoint/parameter/status/raw-response/hash/timestamp audit material and per-source reachability, coverage, freshness, last-success, and last-error state.
- [ ] 6.9 Add recorded/mocked tests for both API versions, missing/untradable sides, malformed schemas, absent coverage, pagination, retry bounds, caching, timestamps, fees, and public-only request routing; verify default tests run offline.
- [ ] 6.10 Add separately marked, default-disabled public smoke tests; run them when preparing phase-2 acceptance and record supported capabilities, observed gaps, and current documentation dates without claiming unavailable league coverage.
- [ ] 6.11 Record phase-2 exit and phase-3 entry evidence for usable public inputs, provenance, migration tests, public-only routing, and source health; retain unmet provider/rule/freshness prerequisites explicitly.

## 7. Phase 3 odds inputs and source admission

- [ ] 7.1 Define `OddsProvider` and causal two-sided snapshot contracts containing vendor/book identities, fixture/shared IDs, participants/orientation, odds format, rules, source/availability/retrieval times, and raw provenance.
- [ ] 7.2 Reuse source allowlist/entitlement/parser/gap conventions through canonical mapping seams; test no Polymarket identifier enters existing Kalshi-specific provider fields.
- [ ] 7.3 Implement provider admission records for coverage, terms, cost, entitlement, rate limits, retention/attribution, and historical data; test credentials alone cannot activate a source.
- [ ] 7.4 Implement labeled manual/import inputs with original source-time validation and raw hashes; test old or unknown-time imports cannot masquerade as fresh odds or multiple books.
- [ ] 7.5 Implement deterministic mock fixtures for complete, missing, stale, conflicting, and malformed sportsbook observations; ensure mock observations cannot appear as live provider data.
- [ ] 7.6 Record whether a concrete vendor is admitted; if explicitly selected, add only its bounded adapter under the protocol and admitted terms, otherwise verify the no-provider/manual workflow completes without a paid request or purchase.
- [ ] 7.7 Add source-specific retention and replay-availability reporting; verify expired/deleted source material is never represented as retained replay evidence and secrets remain redacted.
- [ ] 7.8 Freeze distinct-book deduplication and causal observation-selection rules; test the same sportsbook delivered by two vendors counts once and later-unavailable updates are excluded.

## 8. Phase 3 event and rule matching

- [ ] 8.1 Implement shared stable-ID matching, including `sportradarGameId`, with contradictory league/participant metadata rejection and persisted input/evidence references.
- [ ] 8.2 Implement versioned alias/participant, league, scheduled-time, home-away, and market-type fallback matching with explicit confidence and alternative candidates; test doubleheaders, neutral venues, collisions, and ambiguous names.
- [ ] 8.3 Implement settlement compatibility for outcome orientation, game period/overtime, draws, postponement/cancellation/void, resolution source, and sport-specific material terms; reject unknown or unsupported shapes.
- [ ] 8.4 Persist accepted/rejected/ambiguous match decisions with versions, rules, inputs, and reasons; enqueue unresolved/low-confidence cases for manual review without ranking them.
- [ ] 8.5 Add audited review decisions with actor/time/reason/prior evidence, invalidate approvals after material event/rule changes, and rerun all eligibility gates after review.
- [ ] 8.6 Test ID conflicts, reschedules, timezones, doubleheaders, draw/overtime/retirement/no-contest mismatches, review invalidation, and historical exclusion of match decisions unavailable at the cutoff.

## 9. Phase 3 consensus and deterministic valuation

- [ ] 9.1 Implement supported American-to-decimal conversion and per-book proportional de-vig using both sides; add hand-calculated known-answer and invalid-odds cases.
- [ ] 9.2 Implement the arithmetic mean of at least three distinct admitted fresh two-sided book probabilities; retain each contribution, weight, source count, dispersion, algorithm version, and exclusion reason.
- [ ] 9.3 Apply frozen source-age, pair-skew, cross-source-skew, availability, and market-definition checks; test missing/stale third books and unmodeled three-way odds cannot produce consensus.
- [ ] 9.4 Implement configurable pregame moneyline universe screening by sport/league/date/timezone and maximum horizon; reject live/started/ended/closed/untradable/illiquid/unsupported instruments with explicit reasons.
- [ ] 9.5 Implement quantity-step/minimum/depth-aware executable acquisition costs, gross/net edge, and EV with Decimal fees and nonnegative slippage; test no midpoint, last-trade, or AI-probability substitution.
- [ ] 9.6 Implement inclusive 0.60–0.85 eligibility, 0.70–0.80 preference, and versioned net-edge thresholds never below 0.04; test preferred prices alone cannot qualify and final repriced quantity still passes.
- [ ] 9.7 Implement highest-valid-tick maximum acceptable entry using final size/cost/risk assumptions; test fee-rounding discontinuities and that the next higher tick fails an applicable gate.
- [ ] 9.8 Implement unique event-side ranking by descending net edge, confidence, usable depth, then canonical event/instrument/side identity; keep a stable top five and record overflow dispositions.
- [ ] 9.9 Add complete candidate evidence and multi-reason rejection records, including price/consensus/books/costs/EV/depth/confidence/stake/maximum entry/timestamps/URLs/risks; distinguish completed zero candidates from failed or partial scans.
- [ ] 9.10 Add frozen-input replay tests proving identical scores/order with fixed snapshots, cutoff, reviews, fee/config versions and risk state; preserve chronological holdout provenance without asserting promotion.

## 10. Phase 3 isolated advisory allocations and runtime boundaries

- [ ] 10.1 Implement the separate $50 total/$50 promotional/$0 withdrawable assumption profile, $20 daily all-in exposure, $10 per event, at most three daily slots, and at most $5 for the optional third; verify global/Kalshi defaults are unchanged.
- [ ] 10.2 Implement quantity-aware allocation targeting one or two funded opportunities and allowing zero, with at most three positive stakes among five ranked rows; label the remaining rows unfunded alternatives with reasons.
- [ ] 10.3 Atomically publish positive recommendations with versioned day/event reservations and frozen pre/post risk state; test racing scans cannot both allocate the last slot or overspend remaining capacity.
- [ ] 10.4 Reuse or replace the same event's reservation on refresh while retaining the day's issued exposure/event count across repeats, expiry, and supersession; test a sequence of scans cannot repeatedly allocate a fresh $20.
- [ ] 10.5 Carry outstanding reservations across risk-day rollover against the $50 total, retain historical day state, and keep display timezone changes from resetting capacity; test UTC-default and configured-day/DST behavior.
- [ ] 10.6 Implement audited operator-declared commitments and reconciliation of outstanding advisory assumptions; block positive allocation on unknown/inconsistent capacity and create no fill/position/settlement/PnL ledger rows.
- [ ] 10.7 Read durable global guard state before publication; suppress positive recommendations for halt or unknown guard state while retaining permitted research results and exact reason/time evidence.
- [ ] 10.8 Keep optional existing AI summaries/classification/veto separate from immutable deterministic output; retain model/prompt/output/source/time/cost provenance and visibly unavailable review status without changing probability/rank/stake or granting order authority.
- [ ] 10.9 Test all budget/minimum-size boundaries, repeated/concurrent/day-rollover/reconciliation cases, started-event recheck at publication, halt/unknown state, AI disabled/malformed/proposed override, and absence of order calls.
- [ ] 10.10 Record phase-3 exit and phase-4 entry evidence for matching/consensus/valuation/replay/allocation tests and architecture-class financial review; explicitly retain separate paper, combo, and live promotion gates.

## 11. Phase 4 durable jobs and scanner scheduling

- [ ] 11.1 Implement a scan lifecycle service that freezes request filters, date/timezone/cutoff, config/algorithm/fee/risk versions, inputs, matches, coverage, results, timings, and errors, with atomic candidate/allocation publication.
- [ ] 11.2 Add `scripts/scan_polymarket_sports.py` for manual one-shot scans under existing `uv run python scripts/<name>.py` conventions; test useful exit/status reporting for zero/partial/failed scans.
- [ ] 11.3 Implement stable schedule/slot/filter job keys and explicit manual-request coalescing or serialization; record duplicate/skipped invocations without duplicate successful results or allocations.
- [ ] 11.4 Implement SQLite lease ownership, heartbeat, expiry, and fencing so a reclaimed worker cannot publish; test crash recovery, competing owners, and interrupted pre-publication transactions.
- [ ] 11.5 Implement opt-in morning/pregame/periodic schedules with timezone/DST and bounded missed-run handling; stop refreshing started events and verify installation/dashboard startup does not enable scheduling.
- [ ] 11.6 Bound writers/batches and keep network requests outside database transactions; surface SQLite contention, disk/write errors, missed jobs, and worker/lock health without replacing last-success timestamps.
- [ ] 11.7 Test browser-closed operation, duplicate delivery, worker shutdown/restart, stale-owner fencing, missed schedules, and persistent incomplete-run status; verify existing collectors and paper runners remain foreground-only.

## 12. Phase 4 dashboard and authenticated workflows

- [ ] 12.1 Add scanner query/read models for current and historical scans, filters, candidates, rejections, manual-review queue, watchlist, risk assumptions, and source/job health under existing dashboard ownership.
- [ ] 12.2 Add FastAPI/Jinja scanner pages with venue/sport/league/date/timezone filters, manual refresh, and polling of durable job state; verify browser polling does not spawn independent ingestion workers.
- [ ] 12.3 Add candidate/detail/history views showing full input/cost/stake/reason evidence, conditional maximum entry, unfunded alternatives, frozen historical policy, and completed-zero versus partial/failed outcomes.
- [ ] 12.4 Add authorized watchlist, manual import, match-review, settings, and advisory-reconciliation workflows with actor/time audit and visibly labeled fallback/assumed data.
- [ ] 12.5 Display source ages, coverage, last success/error, stale/degraded states and truthful emergency scope/reason/time; show Polymarket paper unavailable and `No combo` without fabricated results or execution controls.
- [ ] 12.6 Apply existing session auth to every page/data/export/mutation and existing CSRF/origin checks to mutations; validate/escape imported text and redact provider secrets from all responses and logs.
- [ ] 12.7 Test unauthenticated reads/mutations, cross-origin/CSRF rejection, escaped content, secret redaction, empty/stale/error/history truthfulness, manual labels, and halt/unknown-state suppression using the separately fixed snapshot contract.
- [ ] 12.8 Check responsive and accessible scanner views within the existing visual shell and preserve existing dashboard routes/bookmarks and control semantics.

## 13. Phase 4 deployment, recovery, and operator documentation

- [ ] 13.1 Document the supported always-on single-node FastAPI/scanner deployment with persistent local SQLite, least-privilege account, explicit working directory, logs/rotation, clock synchronization, and startup/shutdown; avoid a live database in a concurrently synchronized folder.
- [ ] 13.2 Document and verify Windows Task Scheduler/service and home-server scanner-only operation, disabled defaults, restart behavior, schedule timezone, and browser-closed execution.
- [ ] 13.3 Document private encrypted mesh/tunnel or authenticated TLS reverse-proxy access while preserving application sessions; verify selected topology's certificates, origins, trusted proxy, secure cookies, and inaccessible remote bootstrap conveniences.
- [ ] 13.4 Test direct non-loopback startup rejects missing auth/TLS and the selected remote topology denies unauthenticated and cross-origin requests; record topology-specific limitations before advertising support.
- [ ] 13.5 Document why Vercel is not the primary scanner host under SQLite/serverless duration constraints and list external persistence/durable-worker/distributed-idempotency prerequisites for any future split without implementing it.
- [ ] 13.6 Document consistent backups/restores, additive upgrade verification, interrupted migrations/runs, disable-and-stop rollback, prior-application compatibility, and explicit data implications of backup restoration; rehearse on disposable representative storage.
- [ ] 13.7 Document source admission/retention, deterministic calculations, risk assumptions/reservations/reconciliation, AI advisory limits, honest no-candidate behavior, and separate paper/combo/authenticated/live follow-up gates in the existing docs site.

## 14. Final acceptance and handoff

- [ ] 14.1 Run the full default `uv run pytest -q` suite after implementation and record counts against the dated baseline; resolve introduced failures and keep external integration calls excluded by default.
- [ ] 14.2 Run CI-equivalent `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright src scripts`; record pre-existing failures separately and resolve scanner-related failures.
- [ ] 14.3 Regenerate `.env.example`, verify no drift against authoritative settings, and run the repository's relevant documentation checks for changed operational pages.
- [ ] 14.4 Record public smoke and admitted-provider/manual end-to-end evidence with real coverage/freshness limits; never substitute fixtures for live evidence or declare unperformed deployment checks passed.
- [ ] 14.5 Perform architecture-class review of canonical identity, fee/risk arithmetic, atomic reservations, migration/recovery, remote auth, cross-change ownership, and the absence of paper/authenticated/combo/live implementation paths.
- [ ] 14.6 Validate all five capabilities' scenarios against recorded tests and phase exit evidence; run `openspec validate polymarket-us-and-sports-scanner --strict` and resolve artifact/implementation mismatches.
- [ ] 14.7 Record phase-4 exit with migration/replay/scheduler/browser-closed/security/dashboard/settings/Kalshi regression results and supported deployment limitations; leave any unverified acceptance item open.
- [ ] 14.8 Update the resumable checkpoint with completed tasks, verification, remaining issues, selected model/escalation triggers, and separate follow-up gates; hand off only read-only phases 0–4 without marking paper, combo, or live promotion complete.
