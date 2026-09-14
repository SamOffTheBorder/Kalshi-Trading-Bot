## ADDED Requirements

### Requirement: Council profile lifecycle
Each domain/specialist council profile SHALL have an independently persisted lifecycle of `disabled`, `fixture`, `replay`, `shadow`, `paper_advisory`, or `paper_council`. A profile MUST advance at most one state per explicit promotion and MUST support demotion without deleting history.

#### Scenario: New asset profile is created
- **WHEN** an operator adds a SOL prediction specialist
- **THEN** it starts disabled or fixture regardless of another asset profile's state

### Requirement: Outcome-blind replay
Replay evaluation MUST use frozen candidate and evidence snapshots, MUST preserve original decision-time availability, and MUST withhold settlement, future prices, future evidence, and realized outcome from all agents until their artifacts are final.

#### Scenario: Historical outcome exists in storage
- **WHEN** a replay worker evaluates a settled market
- **THEN** the agents receive only the decision-time bundle and scoring joins the outcome after the council decision is sealed

### Requirement: Shadow mode has no decision influence
In shadow mode, the system SHALL run and score the council beside current strategy/admission behavior while preventing its outputs from changing paper orders, fills, lifecycle, or risk state.

#### Scenario: Shadow council recommends hold
- **WHEN** the base paper path would fill and a shadow council recommends hold
- **THEN** existing paper behavior remains unchanged and the counterfactual disagreement is recorded

### Requirement: Registered baselines and metrics
Every evaluation report MUST compare the council to a no-agent base strategy and a single-agent baseline under the same candidate set. It MUST report artifact validity, timeout rate, abstention/hold rate, citation validity, calibration where applicable, false approvals, false vetoes, realized net result after modeled costs, drawdown, disagreement and error correlation, decision stability, incremental value, latency, and model cost.

#### Scenario: Council appears profitable but costs more
- **WHEN** gross outcome improves but model and execution costs erase the improvement
- **THEN** the report shows non-positive net incremental value and cannot claim the council beat baseline

### Requirement: Pre-registered promotion criteria
The system SHALL freeze evaluation window, sample minimums, metrics, thresholds, evidence manifests, profile/policy/prompts/models, code revision, and random seeds before held-out scoring. Promotion MUST fail when required criteria are missing or any hard threshold fails.

#### Scenario: Thresholds are chosen after results
- **WHEN** a report's threshold registration timestamp follows held-out evaluation
- **THEN** the report is ineligible for promotion

### Requirement: Profile-specific and worst-component promotion
Promotion evidence MUST be scoped to one domain/specialization/profile version. Aggregate success MUST NOT promote an asset, sport, role, or market class whose required component metrics fail.

#### Scenario: BTC succeeds while ETH fails
- **WHEN** a combined crypto report is positive but the ETH specialist fails a required false-approval threshold
- **THEN** BTC may remain eligible while ETH cannot be promoted from that report

### Requirement: Model diversity is measured
Evaluation SHALL record model/provider assignments and compare disagreement, correlated errors, accuracy, latency, and cost. The system MUST NOT treat different role prompts or model names as proof of independence.

#### Scenario: Two models agree on the same errors
- **WHEN** a cross-provider challenger has high agreement but repeats the baseline's false approvals
- **THEN** the report records correlated error and does not credit diversity as incremental value

### Requirement: Domain rollout prerequisites
The initial rollout MUST start with one BTC 15-minute prediction profile in shadow. A perpetual profile MUST remain below shadow influence until real mark, funding, discovery, and candidate-strategy prerequisites pass. A sports profile MUST remain below shadow influence until its narrow sport/league/market class has a qualifying feasibility report.

#### Scenario: Sports feasibility remains insufficient
- **WHEN** no sports profile has a qualifying `research_promising` report
- **THEN** sports council fixture/replay work may continue but it cannot influence paper decisions

### Requirement: Resumable model and run checkpoints
Each completed evidence bundle, agent attempt, verdict, and policy calculation MUST be persisted before the next dependent step. A canceled run or model substitution SHALL resume from validated artifacts and MUST NOT depend on hidden conversational state.

#### Scenario: Master model becomes unavailable
- **WHEN** all specialist verdicts are complete and the configured master fails
- **THEN** the run can retry or resume master synthesis from persisted artifacts under a new recorded attempt without rerunning specialists

## Model Complexity

Evaluation design, temporal masking, metrics, threshold enforcement, and promotion are deterministic. High-complexity challenger configurations use GPT-6 Astra or advisory Claude Opus 5/Fable 5.1; balanced specialists use GPT-5.6 Terra or advisory Claude Sonnet 5; economical baselines and narrow graders use GPT-5.6 Luna or advisory Claude Haiku 4.5. The implementation MUST benchmark at least one strong and one economical configuration and report cost/latency with quality. Anthropic allocations remain advisory until run through an available Anthropic integration; none is available in this session.
