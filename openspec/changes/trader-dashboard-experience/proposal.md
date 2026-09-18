## Why

The dashboard launched by `start_dashboard.bat` has grown into a collection of operational reports: nine top-level navigation links, a long overview, and inconsistent explanations of trading state. A trader needs an immediately legible workspace showing actual engine state, account exposure, actionable opportunities, decision evidence, and the next step when trading is blocked.

## What Changes

- Introduce a responsive trading workspace with persistent account/mode context, navigation, data freshness, alerts, and an accurately scoped halt control.
- Replace the overview report stack with a prioritized Trading Desk: status, risk and P&L, attention queue, positions, watchlist, and decisions.
- Add searchable market discovery and market detail with quote provenance, contract rules, liquidity, settlement timing, and explainable strategy signals.
- Add portfolio, order/fill history, risk, and journal views backed by recorded ledgers; explicitly distinguish paper, shadow, backtest, and future live capabilities.
- Connect Strategy Lab, validation, council evidence, capture health, and jobs into guided workflows with clear blockers and drilldowns.
- Define a cohesive visual system, accessible interactions, trustworthy partial/error states, durable preferences, performance budgets, and staged acceptance criteria.
- Replace misleading intent-only Start/Kill language with capability-derived controls; wire supported paper entry halt through the existing execution/governance path before advertising it as effective.
- Require an authenticated dashboard session for every route before any control (including halt) is wired to real enforcement: an HttpOnly, SameSite session cookie gates the whole dashboard, not just mutating routes. Loopback one-click startup issues a single-use bootstrap token so the browser is authenticated automatically without a manual login step; a non-loopback bind continues to require `DASHBOARD_AUTH_SECRET` (already enforced at launch in `scripts/start_dashboard.py`) and additionally requires it for session login once request auth exists. This resolves the conflict recorded in `reconciliation.md` CONFLICT-1 between `multi-venue-paper-trading`'s fail-closed requirement and this change's own every-view halt requirement.
- Preserve one-click local startup, server-rendered pages, existing bookmarks, and no build or CDN dependency at launch.

## Capabilities

### New Capabilities

- `trader-workspace`: Navigation, visual system, preferences, onboarding, freshness, and responsive accessibility.
- `trader-market-discovery`: Search, watchlists, market detail, quotes, settlement context, and signal explanations.
- `trader-portfolio-review`: Scoped P&L, positions, order/fill history, risk visibility, analytics, and journal exports.
- `trader-operations-workflow`: Truthful engine controls, readiness, alerts, research lineage, jobs, and recovery.

### Modified Capabilities

None. No living capability files were found under `openspec/specs`. Related `operator-dashboard` requirements exist in unarchived changes; this change adds the experience contract and preserves their startup, evidence, risk, and halt intent. Reconcile overlapping changes before implementation rather than inventing MODIFIED requirements against absent main specs.

## Impact

Primary areas: `src/kalshi_bot/web/{app.py,queries.py,control_state.py,operations.py,theme.py,export.py}`, a new session-auth module (middleware/dependency enforcing `dashboard_auth_secret` plus bootstrap-token issuance), `scripts/start_dashboard.py` (bootstrap-token generation and injection into the auto-opened browser URL), templates/static assets, storage read models and small preference/audit migrations, existing risk/emergency-control integration, launcher documentation, and dashboard tests. New routes and read models will be additive. No strategy alpha changes, live order routing, deposits/withdrawals, hosted deployment, or new venue integrations are authorized by this proposal. Any missing execution capability remains visibly unavailable.

## Model complexity

High: the work spans existing ledgers, three market domains, process state, UI interaction, and overlapping changes; incorrect state or aggregation creates material evaluation risk. Use GPT-6 Astra for proposal, design, requirements, task decomposition, and final control/ledger review. The current session provides that model; no model switch is needed. Claude Opus 5 is the advisory Anthropic Pro alternative for these stages; Claude Sonnet 5 or GPT-5.6 Terra may implement bounded presentation tasks after contracts are fixed. See `design.md` for current-source references, allocation, latency/cost tradeoffs, and escalation rules. Anthropic execution is advisory only.

## Checkpoint

Proposal written. Next: CLI design/spec instructions, then design and requirements, then tasks and validation. Authoritative progress is `openspec status --change trader-dashboard-experience --json`; resume without regenerating completed artifacts. Current model: GPT-6 Astra. Escalate to the same high-complexity allocation if control semantics, ledger identities, or cross-change conflicts are unresolved.
