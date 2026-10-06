# Polymarket US + Sports Scanner Integration Report

Date: 2026-09-18  
Change: `polymarket-us-and-sports-scanner`  
Scope of this report: repository audit and planning only; no files under `src/` were modified.

## Executive summary

The repository is much further along than the source brief could verify. It already has a real FastAPI/Jinja dashboard, SQLAlchemy persistence, additive SQLite migrations, lifecycle and promotion gates, multi-domain paper orchestration, Kalshi sports discovery/capture/validation, a sports paper adapter, external-evidence contracts, and advisory local/hosted LLM review. The dashboard is not a stub.

The Polymarket scanner can reuse the safety, provenance, storage, validation, dashboard shell, settings, and test patterns, but the actual cross-venue scanner is still substantial new work. A defensible estimate is:

- about **40% reusable unchanged**;
- about **20% reusable after venue-neutral generalization**; and
- about **40% net new**, chiefly the Polymarket US client, canonical venue model, sportsbook consensus provider, auditable event matching, deterministic candidate scoring, scan persistence, and scanner-specific operations.

The current test baseline is green: **1,012 passed, 3 integration tests deselected, 0 failed, 1 dependency deprecation warning** in 36.82 seconds.

One safety bug from the brief is confirmed. `EmergencyControl.snapshot()` evaluates `self.daily_loss_guard.allows_new_entries` as a bound method instead of calling it. The normal entry gate is correct, but a snapshot without an already-halted control panel can misreport the daily-loss state. This must be fixed and regression-tested in a separate, small change/commit before scanner implementation.

The current Polymarket US documentation also resolves the three disputed facts. Effective 2026-09-17, the exchange-wide taker coefficient is **0.0695**; public unauthenticated access is **20 requests/second per IP**; and fees use **banker's rounding to the nearest cent**.

## 1. Actual repository map

### Application package

| Area | What exists and public surface | Main dependencies and integration role |
|---|---|---|
| `config/` | `Settings` is the configuration source of truth (`settings.py:26`); `get_settings()` (`settings.py:296`); lifecycle states and identity (`lifecycle.py:8,13,31`); crypto registry. | Pydantic Settings. New Polymarket, odds-provider, scanner-risk, and deployment settings must be added here and `.env.example` regenerated. |
| `data/kalshi/` | Public Kalshi client, parsing, and coverage utilities. | `httpx`, storage records. Provides the Kalshi side of a future venue-neutral market-data adapter. |
| `data/l2/`, `data/public_trades/`, `data/brti/`, `data/perps/`, `data/crypto_feeds/` | Point-in-time collectors and source-specific normalization for books, trades, BRTI, perps, and spot bars. | Kalshi/public exchange clients, SQLAlchemy. Strong patterns for observed/available timestamps, gaps, and polling. |
| `data/sports/` | `SportsDiscovery`, discovery rows/config (`discovery.py:45,52,88`); market classifier (`classifier.py:10,22,42`); foreground capture (`capture.py:63,121`); external-provider normalization/conflict/gap contracts (`provider_adapter.py:37,52,62,87,134,142,191,216`); evidence cards/adapters (`evidence.py:18,36,90`); causal flow features (`flow.py:82,97`); chronological feasibility and admission (`validation.py:27,51,65,193,217`). | Kalshi-specific market payloads today, SQLAlchemy sports tables, evidence and validation code. Most reusable research logic is here, but identity and quote inputs need venue-neutral seams. |
| `data/` root | External-source registry, provenance, quality policies, manifests, normalized artifacts, and read-only clients for Binance/Coinbase/Kraken/Gemini/Bitstamp. | `httpx`, Pandas/SQLAlchemy, filesystem artifacts. Reusable patterns for rate limits, retries, provenance, and source comparison. |
| `signals/` | Fee config/calculation (`fees.py:35,70,88`), volatility, Monte Carlo/Black-Scholes, settlement windows, trends, mean reversion. | NumPy/SciPy and canonical strategy inputs. Existing fee code is Kalshi-shaped and must not be reused as the Polymarket formula implementation. |
| `strategy/` | Shared `Action`, `StrategyContext`, `Decision`, and runtime-checkable `StrategyProtocol` (`base.py:20,27,88,160`), plus strategy registry and implementations. | Signals and backtest inputs. The protocol is reusable, but current context fields are prediction/Kalshi oriented and must not parse Polymarket payloads. |
| `backtest/` | Backtest engine, metrics/reporting, walk-forward validation, causal underlying tests, promotion gates, and independent perp ledger. `PromotionPolicy`, `evaluate_promotion`, and `enforce_paper_promotion` live in `promotion_gate.py:11,45,100`. | Strategy protocol, brokers, storage, NumPy/Pandas. Reusable for future scanner validation once snapshots exist. |
| `execution/` | Kalshi client/broker, `BrokerAdapter` and request/result models (`broker_protocol.py:25,40,51,58,66`), `BacktestBroker` (`backtest_broker.py:102`), paper broker/audit/guard/orchestrator, prediction/perp adapters, and `SportsPaperAdapter` (`sports_paper.py:101`). | Broker protocol, storage, risk, Kalshi APIs. The orchestration and paper safety patterns are reusable; `BrokerAdapter` itself is currently Kalshi-specific (`market_ticker`, integer cents) and is not a research-data interface. |
| `risk/` | Fixed-risk and Kelly sizing, daily/consecutive loss guards, drawdown and leverage controls, per-domain paper policies, entry throttles, `EmergencyControl` (`emergency_control.py:44`), and durable cross-domain `GlobalEmergencyControl`/`LifecycleGovernor` (`governance.py:92,291`). | Storage and dashboard control state. Reuse the durable global halt and lifecycle gates; add a separate Polymarket sports bankroll policy without changing Kalshi defaults. |
| `storage/` | SQLAlchemy engine/session setup (`db.py:44,53`), schema creation (`db.py:57`), declarative models (`models.py:36` onward), record helpers, and custom additive SQLite migrations (`migrations.py:7,70`). Current schema version is 16. | SQLAlchemy + SQLite. There is no Alembic. The in-repo migration layer is explicit, idempotent, additive, and tested. New tables must follow it unless a separate migration-tool decision is approved. |
| `web/` | Real FastAPI app factory (`app.py:131`), authenticated sessions, server-rendered Jinja pages, query/read models, operations manager, process controls, theme, exports, and static assets. Sports route exists at `app.py:503`, currently rendering the generic market-area view. | FastAPI, Jinja2, SQLAlchemy. This is the required dashboard host; scanner views should be integrated here, not built as a separate frontend. |
| `ai/` | Forecast/local review plus sports evidence review. `LocalOllamaEvidenceReviewer` defaults to `qwen3:14b` (`sports_research.py:139-151`); `OpenRouterSportsResearch` is opt-in (`sports_research.py:206`) and all output is persisted and advisory. | `httpx`, evidence cards, storage. This already establishes the correct boundary: LLM output may summarize/classify/veto evidence but cannot originate or place trades. |
| `agents/` | Council contracts, roles, persistence, evidence, validation, gateway/coordinator, lifecycle evaluation, and A2A integration. | Storage, AI adapters, execution admission. Useful for audit/review, not required for deterministic scanner ranking. |
| `discovery/` | Registry-driven discovery service. | Config, clients, storage. Pattern can inform multi-venue discovery but is currently crypto/Kalshi oriented. |

### Tests

- `tests/unit/`: 121 Python files covering settings/env synchronization, storage compatibility, Kalshi clients, sports research/paper admission, dashboard auth/queries/operations, risk controls, paper orchestration, and agents.
- `tests/backtest/`: 9 files covering deterministic causal/accounting behavior.
- `tests/integration/`: 2 files; three test cases are excluded by the default `-m 'not integration'` configuration.
- The default suite contains 1,015 collected tests: 1,012 selected and 3 deselected.

### Scripts and launchers

`scripts/` contains foreground entry points for capture, discovery, import, reconstruction, backtests, strategy lab, validation, paper runs, operations, sports feasibility/evidence, and dashboard startup. The project does not define `[project.scripts]`; the convention is `uv run python scripts/<name>.py`. Batch launchers exist for archive, capture, dashboard, and paper flows.

`scripts/start_dashboard.py:34-77` already supports non-loopback binding, but deliberately refuses it without both `DASHBOARD_AUTH_SECRET` and TLS certificate/key paths. This is a useful remote-access foundation.

### OpenSpec

- `openspec/specs/` exists but currently contains no living capability specifications.
- Active changes use `openspec/changes/<kebab-case-name>/{proposal.md,design.md,tasks.md,specs/<capability>/spec.md}`.
- Several changes remain open. The most relevant are `sports-market-feasibility` (15/17 tasks), `sports-evidence-and-flow-research` (17/18), `multi-venue-paper-trading` (83/92), and `trader-dashboard-experience` (5/52).
- The new change must reconcile those artifacts rather than restating their completed Kalshi work as new implementation.

## 2. Reality check against the unverified list

| Claimed item | Verdict | Evidence and implications |
|---|---|---|
| `config/settings.py` | Exists | `Settings` begins at `src/kalshi_bot/config/settings.py:26`; OpenRouter/Ollama settings are at `:223-238`; DB and dashboard auth at `:256-268`. `.env.example` drift test passed. |
| `data/` | Exists and extensive | 49 Python modules across Kalshi, sports, perps, L2, public trades, crypto feeds, provenance, quality, and external sources. Sports discovery/capture/validation is already implemented. |
| `BrokerAdapter` | Exists but needs generalizing | `src/kalshi_bot/execution/broker_protocol.py:66`. Its `OrderRequest` uses `market_ticker` and integer cents (`:25-37`), so it is not venue-neutral. It should remain an execution contract, not be widened into market research. |
| `BacktestBroker` | Exists | `src/kalshi_bot/execution/backtest_broker.py:102`, with market bars and settlement models at `:45,76`. |
| `StrategyProtocol` | Exists | `src/kalshi_bot/strategy/base.py:160`; supporting context/decision at `:27,88`. |
| `signals/fees.py` | Exists, Kalshi-specific | `FeeConfig`/`ResolutionSpec` at `:35,52`; entry fee functions at `:70,88`. Create a separate Polymarket fee implementation behind a venue-specific interface. |
| `risk/`, `EmergencyControl`, `DailyLossGuard` | Exists and broad | `DailyLossGuard` at `daily_loss_guard.py:32`; `EmergencyControl` at `emergency_control.py:44`; durable global governance at `governance.py:92,291`. The reported snapshot bug is real. |
| `storage/` | Exists; no Alembic | SQLAlchemy declarative base at `models.py:36`; many existing models including sports tables at `:796-1027`; custom schema version 16 and additive migration function at `migrations.py:7,70`. |
| `web/` FastAPI dashboard | Exists; not a stub | App factory at `web/app.py:131`; many real routes from `:246`; sports route at `:503`; authenticated sessions and operations/process controls are implemented. Scanner-specific candidate/history/settings views are absent. |
| Phase gates | Exists, partial by domain | Lifecycle is `disabled -> observe -> backtest -> shadow -> paper`, never live (`config/lifecycle.py:8`; `risk/governance.py:241-267`). Backtest promotion gate exists. Several planned sports evidence/shadow gates are still awaiting real captured data. |
| Existing tests and baseline | Exists and green | `uv sync` succeeded. `uv run pytest`: 1,012 passed, 3 deselected, 1 warning, 0 failed in 36.82s. No coverage plugin/report is configured. |

## 3. Confirmed safety bug

`src/kalshi_bot/risk/emergency_control.py:100-107` builds `HaltState`. Line 104 reads:

```python
and self.daily_loss_guard.allows_new_entries
```

The method requires a timestamp and is not called. A bound method is truthy, so `snapshot()` ignores a daily-loss breach unless another guard or the attached control panel already reports a halt. `allows_new_entries(ts)` itself correctly calls the method at line 96. Existing tests verify the entry gate and panel trip, but none directly exercises a daily-loss-only snapshot without a panel (`tests/unit/test_emergency_control.py:39-42,63-68`).

Disposition: create a separate safety change/commit with an explicit snapshot timestamp contract and regression test. Do not bury it in the Polymarket work.

## 4. Primary-source verification

| Question | Verified result on 2026-09-18 | Planning consequence |
|---|---|---|
| Taker coefficient | Polymarket US documents an exchange-wide coefficient of **0.0695**, effective 2026-09-17. [Fee schedule](https://docs.polymarket.us/fees) | Prefer a valid per-market `feeCoefficient` when present, but freeze the effective schedule/source in each scan. Never copy Kalshi fee rounding. |
| Public rate limit | **20 requests/second per IP** for unauthenticated endpoints. [Rate limits](https://docs.polymarket.us/api-reference/rate-limits) | Configure below the limit, cache reference data, use bounded concurrency, stop/retry on 429 with exponential backoff, and prefer streaming where appropriate. |
| Rounding | Fees and rebates use nearest-cent **banker's rounding (half to even)**, including cumulative taker-fill adjustment rules. [Fee schedule](https://docs.polymarket.us/fees) | Implement Decimal-based, known-answer tests at half-cent boundaries and multi-fill cumulative caps. |
| Endpoint shape | Sports-by-league is still `GET /v2/leagues/{slug}/events`; general markets/BBO/book/history use `/v1/...`. [League events](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug), [markets](https://docs.polymarket.us/api-reference/markets/get-markets) | Do not assume one API version for the gateway; type and test each documented endpoint independently. |
| Sports match key | League-event responses expose `sportradarGameId` and the nested event state. [League events](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug) | Prefer provider IDs; fall back to auditable fuzzy matching only when IDs are absent. |
| Combos | Retail combos are beta, authenticated, and require explicit enablement; creation/read uses `api.polymarket.us`, not the public gateway. [Combos API](https://docs.polymarket.us/api-reference/combos/overview) | Combo work cannot be part of the unauthenticated read-only first release. Defer it to a separately approved authenticated research change. |

## 5. Three-bucket classification

### Reusable unchanged

- Settings as source of truth and generated `.env.example` workflow.
- HTTP client patterns, retry/error testing, raw payload provenance, timestamps, gap reports, and source-health concepts.
- Sports classification rules that reject in-play, props, futures, combos, multi-outcome, and unknown-rule markets.
- Chronological validation, feasibility/admission outcomes, and “zero candidates/no trade” semantics.
- Evidence cards, allowlists, LLM audit hashes, and the prohibition on AI-originated trades.
- Durable global emergency halt, lifecycle governance, paper-only guard patterns, and domain-separated reporting.
- SQLAlchemy session factory, additive-migration discipline, dashboard auth/session shell, Jinja/static stack, operations manager, and test conventions.

### Needs generalizing or refactoring

- `BrokerAdapter` and execution records: `market_ticker` and integer-cent assumptions are Kalshi-specific. Generalize only when the later Polymarket paper change needs it; do not use it for read-only data.
- Market identities and existing sports records: add explicit `venue`, external event/market IDs, canonical IDs, and raw payloads; do not reinterpret existing Kalshi rows.
- Quote/order-book models: distinguish canonical decimal prices and venue-native precision from Kalshi cents.
- Fee calculation: introduce a venue-specific interface with independent Kalshi and Polymarket implementations and rounding tests.
- Sports provider normalization: extend from evidence observations to two-sided bookmaker prices, entitlements, freshness, and vig-free consensus.
- Sports discovery/capture/validation: remove implicit Kalshi ticker/payload assumptions at adapter boundaries while preserving current behavior.
- Dashboard labels and queries: “Sports betting” currently reflects Kalshi sports research; add venue-aware filters, candidate details, rejected reasons, health, and history.
- SQLite schema: add venue/canonical IDs and scan records through additive versioned migrations; keep all existing rows readable.

### Must be newly built

- Canonical venue-neutral prediction-event/market/quote/book/resolution/fee/candidate models.
- A read-only `MarketDataAdapter` protocol and Kalshi wrapper.
- The unauthenticated `PolymarketUSMarketDataAdapter` and typed public gateway client.
- Odds-provider protocol plus manual/mock provider and one separately approved concrete provider.
- Event/market matching with provider-ID preference, confidence grades, manual-review queue, and persisted decision inputs.
- Two-sided vig removal, sportsbook consensus, executable-ask/depth checks, fee/slippage-aware EV, and deterministic ranking of zero to five candidates.
- Separate Polymarket sports risk profile and bankroll/exposure/position-count enforcement.
- Scan-run, candidate, rejection, matching, source-health, and odds-snapshot persistence.
- Scanner-specific CLI, scheduling, idempotent concurrency control, dashboard views, and operational/remote-access documentation.

## 6. Proposed package structure

Keep the top-level package name and add venue-neutral boundaries inside it:

```text
src/kalshi_bot/
  domain/
    prediction.py            # canonical IDs, events, markets, quotes, rules
    fees.py                  # protocol/types only; no venue formula
  data/
    market_data.py           # MarketDataAdapter protocol
    kalshi/
      market_data_adapter.py # wrapper over current public clients
    polymarket_us/
      client.py              # public gateway transport, retry, rate limiting
      models.py              # response validation and raw payload retention
      adapter.py             # canonical MarketDataAdapter mapping
      fees.py                # Decimal + banker-rounding implementation
    sports/
      odds.py                # OddsProvider protocol, mock/manual provider
      matching.py            # auditable event and rules matching
      consensus.py           # two-sided vig removal and aggregation
      scanner.py             # deterministic candidate pipeline
      risk.py                # Polymarket sports-specific limits
  storage/
    models.py                # additive venue/scan records initially
    migrations.py
  web/
    queries.py
    app.py
    templates/sports_scanner*.html
scripts/
  scan_polymarket_sports.py
```

If these modules become large, storage and web code can be split later without changing the external contracts.

## 7. OpenSpec conventions and overlap

The repository uses the `spec-driven` schema with proposal, design, per-capability specs, and checkbox tasks. Because there are no living capability specs, this change should introduce new capabilities rather than claim to modify nonexistent main specs.

The proposal should cover phases 0-4 only:

1. venue-neutral read-only domain and fee boundaries;
2. Polymarket US public data and persistence;
3. sportsbook consensus, matching, scanning, and separate risk profile;
4. dashboard, scheduling, and secure remote operations.

Follow-up changes should be separate:

- `polymarket-us-paper-trading` after data/validation/shadow gates pass;
- `polymarket-us-combo-research` only after explicit approval for authenticated beta API access;
- any live execution change only after separate human approval and go/no-go evidence.

Before implementation, reconcile overlapping open tasks so this change consumes completed sports and dashboard contracts rather than duplicating them.

## 8. Deployment and remote access recommendation

The dashboard can already bind beyond loopback with TLS and a configured secret. Remote access is therefore feasible without a frontend rewrite.

**Recommended first deployment:** run the existing FastAPI app and scanner worker on one always-on machine with the current persistent SQLite database, and reach it privately through a secure mesh/tunnel such as Tailscale or an authenticated reverse proxy. This preserves the single-writer/local-database assumptions and lets the scanner continue while the browser is closed.

**Vercel recommendation:** do not make Vercel the primary scanner host. Vercel can deploy FastAPI, but Python runs as bounded functions; cron invocations have function duration limits; and Vercel explicitly says local SQLite is not supported because function storage is ephemeral. A proper Vercel deployment would therefore require a managed database, external durable worker/queue, distributed locks/idempotency, and likely a split between the dashboard and scanner service. That is more architecture than the first release needs. See [Vercel FastAPI](https://vercel.com/kb/guide/ship-a-fastapi-app-on-vercel), [function duration](https://vercel.com/docs/functions/configuring-functions/duration), and [SQLite support](https://vercel.com/kb/guide/is-sqlite-supported-in-vercel).

If a public managed deployment is preferred later, use an always-on container host plus managed Postgres. Vercel can remain an optional edge/dashboard target after the storage and worker boundaries are deliberately redesigned; it is not required for access from other places.

## 9. AI/model recommendation

The AI should **not** be the trade decider. Candidate qualification should be deterministic and replayable: event match, rules compatibility, at least three current two-sided books, vig-free consensus, executable Polymarket ask/depth, fees, slippage, risk limits, and minimum edge. The LLM may summarize captured evidence, identify conflicts, or veto a candidate; it must never invent a probability, originate a trade, size it, or bypass a failed rule.

For the first release, no paid model is required. The current local Ollama adapter can provide optional summaries, and the scanner remains complete when AI is unavailable. If hosted review is later enabled:

- use a cost-sensitive structured-output model such as GPT-5.6 Luna for routine evidence classification;
- escalate ambiguous/high-impact reviews to GPT-5.6 Terra, GPT-5.6 Sol, or GPT-6 Astra only after an evaluation proves the improvement is worth the cost;
- Claude Sonnet 5 is the comparable advisory implementation/review default; Claude Opus 5 is reserved for difficult architecture or safety review;
- record provider, exact model, prompt/output hashes, latency, citations, and cost; fail closed on malformed or unavailable output.

OpenAI's current guidance positions GPT-6 Astra for the hardest reasoning, GPT-5.6 Terra for balanced intelligence/cost, and GPT-5.6 Luna for cost-sensitive high-volume work. API use requires an API key and usage billing; a ChatGPT/Codex subscription is not an application API allowance. See [OpenAI model guidance](https://developers.openai.com/api/docs/models), [API pricing](https://developers.openai.com/api/docs/pricing), and [API quickstart/billing](https://platform.openai.com/docs/quickstart/make-your-first-api-request).

## 10. Package rename recommendation

Defer the `kalshi_bot` rename. The name is increasingly inaccurate, but changing it now would touch imports, tests, packaging, docs, scripts, generated configuration references, and open specs while the venue boundaries are still moving. Add venue-neutral modules inside `kalshi_bot`, then perform a mechanical one-change rename only after the Polymarket public-data and scanner contracts stabilize.

## 11. Ranked technical risks

1. **False event/market equivalence.** Similar names or start times do not prove matching resolution rules. Provider IDs and persisted rule comparison must precede ranking.
2. **Cost-model errors.** Per-market coefficients, Decimal precision, banker rounding, per-fill/cumulative rules, spread, depth, and slippage can erase apparent edge.
3. **Overlapping active OpenSpec work.** Several sports/dashboard/paper changes are incomplete; duplicated or contradictory contracts would create unsafe parallel paths.
4. **Historical-data insufficiency.** Existing sports work reports many discovery rows but zero sports candles, so no honest validation/promotion is yet possible.
5. **Odds-provider legality, entitlements, cost, retention, and history.** A concrete vendor cannot be selected solely on API shape.
6. **Schema identity migration.** Venue-neutral IDs must be additive; existing `market_ticker` rows cannot be silently reinterpreted.
7. **Stale or partial data displayed as healthy.** Source health must be computed from persisted timestamps and errors, not a successful page load.
8. **Remote exposure/security.** Public access needs TLS, authentication, secret rotation, least privilege, and no mutation endpoint that bypasses the global halt/admission path.
9. **Scheduler duplication and SQLite contention.** Scheduled scans need idempotency/locking and bounded writers; Vercel-style duplicate cron delivery would require a different persistence design.
10. **AI automation creep.** An LLM recommendation must remain advisory and never become an untracked probability or execution authority.
11. **Confirmed snapshot safety bug.** Fix separately before relying on snapshot state in a remote dashboard.
12. **Combo scope conflict.** Current combo APIs are authenticated beta; they cannot honestly ship inside the public, no-credentials phase.

## 12. Open questions and recommended defaults

| Decision | Recommended default |
|---|---|
| Remote access topology | One always-on home/server process plus private Tailscale-style access first. Keep Vercel out of the critical path. |
| Odds provider | Build protocol + mock/manual import first; evaluate The Odds API and OpticOdds on league coverage, historical snapshots, terms, rate limits, retention, and price before selecting one. |
| Hosted AI purchase | Do not buy credits for the initial scanner. Add a small capped API budget only after deterministic scanning works and an evaluation shows hosted review adds measurable value. |
| AI authority | Advisory summary/veto only; deterministic rules remain the decider and the human remains the final approver. |
| Initial scope | Pregame moneyline only, config allowlist, no in-play, props, spreads, totals, futures, or combos. |
| Storage | Continue the tested additive SQLite migration path for the single-node release. Treat Postgres/Alembic or another migration stack as a separate deployment decision. |
| Change split | Use this OpenSpec change for read-only phases 0-4; separate paper, combo/authenticated research, and live execution changes. |
| Existing sports evidence | Reuse it as optional contextual evidence, not as sportsbook consensus and not as a substitute for executable odds. |
| Bankroll defaults | Keep the proposed Polymarket sports bankroll/risk values separate from all Kalshi/global settings and require config plus tests for every limit. |

## 13. Model complexity and handoff

Complexity is **high**: the change spans public APIs, canonical identity, financial arithmetic, fuzzy joins, storage migration, scheduling, remote security, dashboard truthfulness, and multiple active OpenSpec changes. Errors can create false edge or misleading safety state.

Recommended planning/review allocation:

- GPT-6 Astra or Claude Opus 5 for architecture, fee/risk semantics, identity/migration review, and final acceptance review.
- GPT-5.6 Sol/Terra or Claude Sonnet 5 for bounded implementation slices once contracts are fixed.
- GPT-5.6 Luna or Claude Haiku 4.5 for mechanical fixtures, schema mapping, and documentation, with stronger-model review for money/risk paths.
- Escalate whenever a task changes canonical identity, rounding, risk/admission, migration, remote auth, or execution authority; do not downgrade those reviews for latency or cost.

Authoritative checkpoint: `openspec status --change polymarket-us-and-sports-scanner --json`. Next planning artifacts are governed by the OpenSpec CLI. No implementation is authorized by this report.

## 14. Apply authorization and safety prerequisite status

On 2026-09-18, the operator responded by issuing `$openspec-apply-change polymarket-us-and-sports-scanner`. This records delivery and acceptance of the report as the source brief requires before application implementation.

The remaining independent safety prerequisite is **not met**. Reinspection found `EmergencyControl.snapshot()` still references `self.daily_loss_guard.allows_new_entries` without invoking it, the current emergency-control tests do not cover a daily-loss-only/no-control-panel snapshot, `openspec list --json` has no dedicated safety change, and available branch/recent commit history contains no independent fix evidence. The scanner change must not absorb that correction. Create and complete a separately scoped safety change/commit/PR with a timestamp-aware snapshot contract and regression test, then record its commit/PR and test evidence here before Phase 1 source edits begin.
