# Agentic trading council

The council reviews a candidate emitted by an existing prediction, perpetual,
or sports strategy. It does not scan for trades, create direction, or receive
a broker, credential, lifecycle, bankroll, or risk-mutation tool.

## Roles and evidence

Each profile declares researcher, bull thesis, bear thesis, skeptic,
execution/liquidity, rules/settlement, portfolio risk, and master synthesis
roles. The first round is blind and concurrent. Every claim cites an immutable
evidence ID from the decision-time bundle; missing, conflicting, stale, or
injected source text causes abstention or a deterministic hold.

The deterministic policy owns quorum, critical-role completion, vetoes,
deadlines, sizing bounds, and final admission. The master can recommend
`take`, `hold`, or `reject`, but cannot clear a veto or cite an unknown
artifact. There is at most one format repair and one optional reconsideration
round.

## Profiles and lifecycle

Profiles use hierarchical keys such as `prediction/BTC/15m`,
`perp/BTC/directional`, and `sports/NFL/game/moneyline`. Lifecycle is stored
append-only and advances one step at a time:

`disabled` → `fixture` → `replay` → `shadow` → `paper_advisory` → `paper_council`

Promotion requires a frozen, profile-specific evaluation report and an
explicit operator. Demotion preserves prior rows. The initial BTC 15-minute
profile is fixture-only unless an operator advances it after evaluation.

## A2A configuration

The pinned `a2a-sdk==1.1.2` dependency is used with protocol version `1.0`.
Remote cards must be HTTPS, host-allowlisted, version-compatible, signed when
configured, and declare the assigned council skill plus JSON input/output
media. Only typed verdict Artifacts are durable. Authentication is injected
outside cards and logs. Disable remote transport with the explicit operator
switch to use the in-process fallback; history is retained.

## Evaluation and promotion

Outcome-blind replay passes only frozen candidate/evidence inputs to agents and
joins realized outcomes after artifacts are sealed. Every report compares the
same sample set against no-agent and single-agent baselines, including validity,
timeouts, holds, citation validity, calibration, false approvals/vetoes,
net-after-cost, drawdown, stability, disagreement/error correlation,
latency, and model cost. Thresholds, windows, manifests, prompts, models,
code revision, and seed are frozen before held-out scoring. A failing asset,
role, sport, or market component blocks that profile even if an aggregate is
positive.

## Final configuration record

The implementation benchmark is currently a deterministic fixture/conformance
benchmark, not a claim of live model performance. The chosen default matrix is:

- researcher and master: `GPT-6 Astra` (strong reasoning tier)
- market specialists, skeptic, rules/settlement, and execution/liquidity:
  `GPT-5.6 Terra` (economical tier)
- `GPT-5.6 Luna` is reserved for future challenger comparisons
- Anthropic is advisory-only in the profile matrix and was not exercised because
  no Anthropic integration is configured

These assignments are cost and latency hypotheses until a frozen held-out report
is registered for a profile. They cannot advance a profile or enable paper
influence by themselves.

## Inspection

Use `council <run-id>` for a redacted JSON lineage dump, or
`council-profile [profile-id]` for configured profiles and lifecycle history.
The dashboard's `/council` page exposes the same read-only lineage from
evidence bundle through final deterministic decision.

No council mode is available for live execution. `paper_advisory` can only
hold an otherwise eligible candidate or tighten its price/size; it cannot
originate direction, increase risk, loosen price, or revive a refusal.
