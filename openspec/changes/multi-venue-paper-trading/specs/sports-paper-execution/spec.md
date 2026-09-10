## ADDED Requirements

### Requirement: Sports paper execution has an evidence prerequisite
The system SHALL keep sports paper execution disabled by default. It SHALL refuse sports-paper startup unless a completed, versioned feasibility report for the exact market class and strategy has a pre-registered `research_promising` verdict, sufficient causal observations, fixed holdout/thresholds, realistic fill/cost analysis, and no unresolved integrity/reconciliation issue. An `insufficient_data`, `park`, legacy, or diagnostic-only result SHALL block paper admission.

#### Scenario: Sports research has no sufficient capture
- **WHEN** the latest combined sports report is `insufficient_data`
- **THEN** a sports paper command SHALL refuse startup and display the evidence gate failure

#### Scenario: Candidate changes after feasibility
- **WHEN** an operator changes the sport, market shape, model version, or execution assumptions after a promising report
- **THEN** the system SHALL require a new matching feasibility report before paper admission

### Requirement: Narrow sports pilot admission
The initial sports paper adapter SHALL admit only pre-game, single-game, two-outcome Kalshi sports contracts explicitly covered by the approved pilot. It SHALL verify market rules, official settlement authority, event start/close time, sport/league, market classification, eligibility/liquidity snapshot, strategy version, source/evidence freshness, and independent risk budget at decision time. Futures, player props, parlays/combos, in-play markets, and unclassified shapes SHALL be rejected.

#### Scenario: In-play market is discovered
- **WHEN** a candidate sports contract is already in play
- **THEN** the system SHALL reject it as outside the initial pilot before strategy execution

#### Scenario: Approved pre-game market has stale data
- **WHEN** its quote, odds, lineup, or required evidence exceeds the configured freshness limit
- **THEN** the adapter SHALL record a HOLD/blocked decision and create no paper order

### Requirement: Sports evidence and external-provider provenance
The system SHALL accept sports odds, lineup, injury, score, or research inputs only through versioned provider adapters with an explicit allowlist, entitlement/terms record, source URL, provider event/market mapping, observed/available/retrieved timestamps, raw content hash, parse version, quality status, and conflict status. Provider data SHALL be causal at decision time. The LLM may summarize eligible captured evidence but SHALL not search unrestricted sources for an execution decision, create an untracked feature, or alter a strategy/risk decision.

#### Scenario: Two eligible providers conflict
- **WHEN** two captured sources state incompatible pre-game information
- **THEN** the system SHALL mark the relevant evidence conflicted and block a dependent entry unless the pre-registered resolution rule selects one source

#### Scenario: Evidence arrives after game start
- **WHEN** a valid external observation was retrieved after the market's decision cutoff
- **THEN** the adapter SHALL retain it for research but SHALL exclude it from that paper decision

### Requirement: Conservative sports binary simulation and settlement
The sports adapter SHALL use the binary paper-execution semantics for YES/NO pricing only after the sports admission checks pass: causal side-aware quotes, documented fees, observable liquidity caps, marketable limit protection, explicit rejection reason, official Kalshi result, and durable restart reconciliation. It SHALL not assume a fill based on a later quote, model a maker fill without validated evidence, or substitute a third-party score for official Kalshi settlement.

#### Scenario: Sports order has no fillable two-sided quote
- **WHEN** the strategy proposes a YES or NO entry and the required causal quote side is absent
- **THEN** the adapter SHALL reject the paper order with `no_fillable_quote`

#### Scenario: Position survives a process restart
- **WHEN** the sports runner restarts with an open position and Kalshi has published an official result
- **THEN** it SHALL settle from the official result and preserve the complete evidence/quote/decision lineage

### Requirement: Copy-trading prohibition
The system SHALL not implement copy trading, trade copying, account tracking, or inference of another participant's identity from public trades. Public anonymous trade/order-flow observations may be used only as aggregate, non-identifying features with causal timestamps and documented feature versions. A future attributed, lawful data integration requires a separate approved change, provider/terms review, and evidence gate.

#### Scenario: Strategy requests a copied counterpart trade
- **WHEN** a sports strategy returns an instruction attributed to another trader or account
- **THEN** the system SHALL reject it with `copy_trading_unsupported`
