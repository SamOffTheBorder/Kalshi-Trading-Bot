## Why

The bot can generate domain-specific candidates, but a candidate can still be researched, argued, and effectively approved by one reasoning path. Reusing LarpQuest's independent validation, typed verdict, bounded-retry, and escalation pattern gives prediction, perpetual, and sports paper trades an auditable council of specialists before the existing deterministic admission and risk gates decide whether a trade may proceed.

## What Changes

- Add a market-domain router that sends each candidate to a prediction, perpetual, or sports council, then to an asset specialist for crypto or a sport/league specialist for sports.
- Add independent research, bullish, bearish, skeptic/red-team, execution/liquidity, risk/portfolio, and rules/settlement roles. Roles receive the same immutable as-of evidence bundle and return schema-validated verdicts with evidence references, confidence, objections, and abstentions.
- Add a master decision agent that synthesizes the independent verdicts into `take`, `hold`, or `reject`, including proposed side, size ceiling, invalidation conditions, and unresolved dissent. It cannot override deterministic data-quality, freshness, lifecycle, liquidity, bankroll, paper-safety, or portfolio-risk gates.
- Add bounded reconsideration: one critique/revision round is permitted when required evidence is missing or verdicts conflict; unresolved conflicts, malformed outputs after retry, agent failures, or quorum failure produce `hold`.
- Add Agent2Agent (A2A) interoperability for independently deployable agents through version-pinned Agent Cards, task lifecycles, structured artifacts, authentication, timeouts, and capability checks. The first implementation may run agents in-process behind the same contract before distributing them.
- Add append-only council audit records, cost/latency budgets, prompt/model/schema versions, replay support, and evaluation reports measuring calibration, disagreement, incremental value, and decision quality against single-agent and no-agent baselines.
- Roll out in shadow mode first, beginning with one narrow BTC prediction council, then BTC perpetuals, then a pre-qualified sports pilot. Council approval never promotes a market or enables live execution.

## Capabilities

### New Capabilities

- `trade-council-orchestration`: Domain routing, specialist selection, independent role execution, bounded reconsideration, quorum, synthesis, and fail-closed outcomes.
- `agent-verdict-contracts`: Immutable evidence bundles and schema-validated, evidence-linked research, thesis, critique, risk, execution, rules, and final-decision artifacts.
- `a2a-trading-interoperability`: Version-pinned A2A discovery and task exchange for trading agents, including identity, authorization, timeouts, idempotency, and protocol audit metadata.
- `deterministic-agent-admission`: The ordering and authority boundary between probabilistic council recommendations and existing deterministic paper-admission, safety, and portfolio-risk controls.
- `agent-council-evaluation`: Replay, shadow comparison, calibration, disagreement, latency/cost measurement, model/prompt versioning, and promotion criteria for each domain/specialist council.

### Modified Capabilities

None. The repository currently has no living capability specs under `openspec/specs`; this change introduces additive contracts and preserves the requirements in active paper-trading changes.

## Model Complexity

The first release needs model diversity only where independent judgment can change the result. Research synthesis and the master decision are high-complexity, long-context tasks; bullish/bearish theses and settlement interpretation are medium-to-high; evidence-shape validation, routing, and most deterministic checks are code or low-complexity model work. Runtime model IDs remain configuration, are pinned per council run, and must be selected by measured evals rather than personality labels alone.

As of proposal time, the recommended OpenAI/Codex Pro starting points are GPT-6 Astra for master synthesis and difficult research, GPT-5.6 Terra for thesis and specialist work, and GPT-5.6 Luna for high-volume classification. The Anthropic advisory alternatives are Claude Fable 5.1 for the hardest long-horizon synthesis, Claude Opus 5 for complex agentic reasoning, Claude Sonnet 5 for specialist agents, and Claude Haiku 4.5 for narrow validation. This session has no Anthropic subagent, so those assignments are architecture guidance, not executed validation. The current model writes the planning artifacts; implementation must benchmark at least one strong and one economical configuration before promotion.

## Impact

- New code is expected under `src/kalshi_bot/agents/`, with integration points in `ai/`, `execution/orchestrator.py`, domain adapters, risk governance, storage models/migrations, operator CLI, and dashboard queries/templates.
- New append-only records will link council runs and artifacts to paper run, candidate, market, evidence-manifest, policy, prompt, model, and A2A task identifiers.
- A2A SDK/server dependencies may be added only after a version and conformance fixture are pinned; the internal contracts must not depend on transport-specific types.
- Model and research calls add latency and variable cost, so every role has deadlines, token/cost ceilings, concurrency limits, and an explicit fail-closed policy.
- No production credentials, live-order capability, or automatic lifecycle promotion is added. Initial outcomes are shadow recommendations and, only after evaluation, inputs to existing paper-trading admission.
