## Why

The repository already has Kalshi sports research, paper infrastructure, and an authenticated FastAPI dashboard, but its market identities and sports joins remain Kalshi-specific and it has no Polymarket US public-data or deterministic sportsbook-consensus scanner. This change adds an auditable, read-only way to evaluate eligible sports opportunities while preserving existing Kalshi behavior and the evidence gates required before future execution.

## What Changes

- Deliver phases 0–4: integration report and baseline; venue-neutral research contracts; Polymarket US public ingestion; deterministic odds consensus, matching, ranking, and advisory sizing; dashboard, scheduling, and secure remote operations. Record migration, test, entry, and exit plans before implementation, preserving the brief's report-and-human-response gate before editing application code.
- Introduce canonical venue/event/instrument identities, quotes, books, rules, provenance, and a read-only `MarketDataAdapter`, with a compatibility wrapper around existing Kalshi public data. Keep API payload parsing in adapters and research separate from execution-oriented `BrokerAdapter`; do not rename `kalshi_bot` or reinterpret historical Kalshi rows.
- Add an unauthenticated Polymarket US gateway client with documented endpoint capability discovery, pagination, timeouts, caching, bounded retries/rate limits, stale-data rejection, and raw-response auditing. Preserve venue-specific fee formula, coefficient, effective-date/source, and rounding semantics; verify disputed fee and rate-limit claims against primary documentation before implementation.
- Add an `OddsProvider` boundary, manual/imported and test inputs, and an optional explicitly configured provider integration. Rank only confidently matched, compatible pre-game moneyline markets with fresh two-sided prices from at least three distinct sportsbooks, a usable executable ask and depth, and fees and slippage included. Prefer shared stable event IDs; persist matching evidence and route ambiguous joins to manual review. Unsupported settlement shapes, including unmodeled draws, are ineligible.
- Produce zero to five replayable candidates with net edge/EV, confidence, liquidity, recommended stake, maximum acceptable entry price, timestamps, reasons, and risks. Persist rejected candidates too. Use deterministic calculations; LLM research remains advisory and cannot originate or size scanner candidates.
- Add an isolated advisory sports budget: $50 total, initially classified as $50 promotional and $0 withdrawable, $20 daily exposure, $10 per event, at most three daily positions, and at most $5 for an optional third. These are operator assumptions, not authenticated balances. Retain the 60–85¢ eligible band, 70–80¢ preference, and at least four percentage points of net edge; a price preference never establishes edge. Keep aggregate sizing coherent across refreshes and do not change global/Kalshi bankroll settings.
- Extend the existing dashboard with filters, freshness/source health, candidates, watchlist, rejections, risk assumptions, history, and truthful emergency-control status. Add manual and opt-in scheduled scans that work with the browser closed, plus Windows/home-server and authenticated, encrypted remote-access guidance. Scope unattended operation to this read-only scanner; existing collectors and paper runners retain their foreground-only contracts.
- Defer Polymarket paper execution and performance ledgers, authenticated trading/credentials, and combo creation or executable quotes requiring the authenticated beta API to separate changes. Display unsupported features honestly, with “No combo” as the default. No breaking changes are intended.

## Capabilities

### New Capabilities

- `multi-venue-market-domain`: Canonical research identities, market-data contracts, venue-specific fee semantics, provenance, and backward-compatible Kalshi adapters.
- `polymarket-us-public-data`: Resilient, unauthenticated sports market discovery, quotes/books/history where supported, auditing, and source health.
- `sports-odds-consensus`: Provider admission/provenance, causal two-sided odds, deterministic vig removal, and auditable event/rule matching.
- `sports-candidate-scanner`: Eligible-universe screening, reproducible net-edge ranking, isolated advisory risk sizing, rejections, and valid zero-candidate results.
- `sports-scanner-operations`: Additive persistence, dashboard workflows, scheduled scanner lifecycle, health, settings, and secure remote-access operations.

### Modified Capabilities

None. `openspec/specs/` has no living capabilities; related requirements currently reside in open changes.

## Impact

Primary areas are `data/kalshi`, `data/sports`, new venue-neutral/public-data modules, `signals/fees.py` compatibility boundaries, isolated sports risk policy, `storage/{models,migrations}.py`, `config/settings.py`, dashboard queries/routes/templates, operator scripts, tests, and Docusaurus operations documentation. Extend the existing additive SQLite migration mechanism rather than introducing Alembic by assumption. Settings remain authoritative and `.env.example` is regenerated. Provider secrets stay server-side; this change requires no Polymarket credentials or new paid subscription.

Reconcile `sports-market-feasibility` and `sports-evidence-and-flow-research` for provenance/holdout and advisory-LLM boundaries; `multi-venue-paper-trading` retains ownership of execution ledgers and promotion; `trader-dashboard-experience` retains shared authentication, truthful state, and UI contracts. Remote scanner access must preserve session authentication, CSRF/origin checks, and encrypted transport. The confirmed `EmergencyControl.snapshot()` daily-loss method-reference defect belongs in a separate fix/commit/PR with regression coverage, not this feature's implementation.

## Model complexity

High: identity and financial-unit boundaries, temporal correctness, provider uncertainty, migration compatibility, security, and overlapping changes require broad context and tool-assisted verification. Planning and acceptance review favor correctness over latency; bounded implementation can reduce cost once contracts stabilize. Use GPT-6 Astra for architecture, safety/security, requirements, task decomposition, and final integration review; GPT-5.6 Sol or Terra for bounded implementation/review; GPT-5.6 Luna for mechanical, high-volume work under fixed contracts. Anthropic advisory alternatives are Claude Opus 5 for architecture and Claude Sonnet 5 for bounded implementation; verify actual account availability before selection and do not imply Anthropic execution occurred. Carry this allocation into downstream artifacts. Escalate to Astra/available architecture-class equivalent for uncertain financial units, rule equivalence, security or ledger changes, cross-change conflicts, or two failed attempts at the same scenario; never relax acceptance criteria to accommodate a model limit.

## Checkpoint

Proposal complete; selected planning allocation: GPT-6 Astra. Repository/source brief and overlapping proposals were inspected, and the CLI proposal contract was followed; design, capability specs, tasks, and full change validation remain pending. Test baseline and external-source findings belong in the integration report and must not be inferred from this proposal. Provider choice/entitlement, verified fee/rounding/rate-limit semantics, and remote deployment configuration require explicit treatment in design, with fail-closed defaults. Resume with `openspec status --change polymarket-us-and-sports-scanner --json`, then the ready design/spec instructions; read this proposal, the integration report, and the four related changes above before continuing. Preserve completed artifacts when switching models; use the escalation triggers above and retain the source brief's implementation gate.
