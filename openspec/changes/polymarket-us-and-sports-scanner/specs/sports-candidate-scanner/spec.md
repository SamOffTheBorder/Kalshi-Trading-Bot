## ADDED Requirements

### Requirement: Supported pregame universe
The scanner SHALL operate on a configurable sport/league allowlist and selected local date/timezone with a bounded maximum time to event. Defaults SHALL cover MLB, NFL, NCAA football, NBA, WNBA, NHL, major soccer, ATP/WTA tennis, and major MMA/boxing only where supported liquid listings and compatible two-outcome moneylines exist. It SHALL exclude in-play, ended, closed, untradable, long-dated, unsupported, and illiquid instruments, including spreads, totals, props, futures, and combos. Obscure esports, darts, table tennis, and minor leagues SHALL remain disabled unless explicitly configured; enabling a league MUST NOT bypass market-shape or liquidity gates.

#### Scenario: Allowlisted event becomes live during a refresh
- **WHEN** event state indicates in-play or the scheduled start has passed before candidate publication
- **THEN** the candidate is rejected or invalidated and the reason is retained

#### Scenario: Allowlist contains soccer without compatible two-outcome rules
- **WHEN** discovered markets require unmodeled draw semantics
- **THEN** the scanner records unsupported coverage and emits no candidate for those markets

### Requirement: Complete qualification and cost-aware calculations
A ranked candidate SHALL require a confident compatible match, at least three distinct fresh two-sided books, causal consensus, fresh executable ask, tradable side, usable size/depth, verified effective fees, and a nonnegative configured slippage allowance. Calculations SHALL use decimal units for one-dollar binary payout: gross edge equals consensus probability minus executable ask; net edge equals consensus probability minus all-in per-contract cost; expected value equals quantity times consensus payout minus total estimated acquisition cost. Depth-based pricing, rounded total fees, minimum quantity, and quantity increments SHALL be recomputed for the proposed size. Candidates SHALL retain the assumptions and MUST NOT substitute midpoint, last trade, or an LLM probability for executable price or consensus.

#### Scenario: Gross edge disappears after costs
- **WHEN** a candidate has positive gross edge but fees and slippage reduce net edge below its threshold
- **THEN** the candidate is rejected with the fee, slippage, and net-edge calculation recorded

#### Scenario: Best ask lacks enough depth for the proposed size
- **WHEN** the proposed quantity exceeds available size at the quoted ask
- **THEN** the scanner uses documented book depth to reprice and revalidate the complete size or reduces/rejects the size rather than pricing all contracts at the best ask

### Requirement: Price bands and maximum acceptable entry
Default permitted executable asks SHALL be 0.60 through 0.85 inclusive, with 0.70 through 0.80 preferred and a minimum net edge of 0.04. A versioned policy SHALL specify the edge requirement within and outside the preferred band, and no band SHALL lower the minimum below 0.04. Preferred prices SHALL never establish qualification independently. Each candidate SHALL expose the highest tick-valid entry price that still satisfies its edge, fee, slippage, size, and risk assumptions, bounded by the permitted range; that value SHALL be labeled a conditional limit rather than a promise of execution.

#### Scenario: Preferred price has no edge
- **WHEN** an ask is 0.75 but net edge is less than 0.04
- **THEN** the market is rejected despite lying in the preferred band

#### Scenario: Maximum acceptable price crosses a fee rounding boundary
- **WHEN** entry-price search encounters a change in rounded fee
- **THEN** the resulting maximum is recomputed on valid ticks and the next higher tick fails an applicable condition

### Requirement: Reproducible zero-to-five ranking
The scanner SHALL publish zero to five unique candidates with a versioned deterministic sort and tie-break rule. The default ordering SHALL use descending net edge, descending confidence, descending usable liquidity, then canonical event/instrument/side identity. It SHALL deduplicate equivalent event-side opportunities and retain the disposition of qualifying overflow candidates. Identical input snapshots, scan cutoff, matching/review decisions, fee schedule, policy, and advisory risk state SHALL produce identical scores, order, and stakes. Zero candidates SHALL be a valid completed result with reasons, distinct from a failed or incomplete scan.

#### Scenario: No market qualifies
- **WHEN** every discovered market fails a qualification rule
- **THEN** a completed scan contains zero ranked candidates and the evaluated-market rejection reasons without forced recommendations

#### Scenario: More than five candidates qualify with ties
- **WHEN** six eligible candidates include equal scores
- **THEN** the documented tie-break rule selects a stable top five and records the remaining candidate as outside the output limit

### Requirement: Complete candidate and rejection evidence
Each candidate SHALL include venue, sport/league, event, side, canonical and venue market IDs, market URL, executable ask and implied probability, consensus probability and book count, gross edge, fee, slippage, net edge, expected value, depth/liquidity, confidence, recommended stake and quantity, maximum acceptable entry, primary reasons/risks, source timestamps, and input/policy references. Every evaluated exclusion SHALL retain stable reason codes and evidence sufficient to explain the failed gate. Candidate text MUST NOT claim safety, a guarantee, or an investment return.

#### Scenario: User inspects a rejected candidate
- **WHEN** the market failed both freshness and rule compatibility
- **THEN** the stored result exposes both known failure reasons and their input references rather than an unexplained empty rank

### Requirement: Isolated advisory bankroll and coherent allocation
The scanner SHALL use a separate Polymarket sports policy defaulting to a $50 total budget, $50 promotional and $0 withdrawable, a $20 daily exposure cap, $10 per-event cap, and at most three daily positions. One or two positions SHALL be the normal target; an optional third SHALL be capped at $5. Budget, exposure, and per-event checks SHALL include all estimated acquisition costs. These values SHALL be labeled operator assumptions, not authenticated balances or positions. The scanner MUST NOT change global/Kalshi risk settings, chase losses, or create fills, settlements, or execution ledger entries.

#### Scenario: Third recommendation is allocated
- **WHEN** a third funded advisory slot is considered after two earlier slots
- **THEN** its all-in stake is at most $5 and total daily and event exposure remain within their respective caps

#### Scenario: Five ranked candidates exceed position capacity
- **WHEN** five opportunities qualify but only three funded slots are permitted
- **THEN** at most three receive positive recommended stake and the others are explicitly unfunded alternatives

### Requirement: Durable daily advisory state and refresh safety
Advisory allocation SHALL use a persisted day/timezone-scoped state with stable event identities, allocation version, and operator-declared committed exposure when provided. Repeated or concurrent scans SHALL replace or reuse an active recommendation allocation atomically rather than add phantom positions or independently allocate the whole daily budget. Committed assumptions SHALL persist until explicitly amended with audit evidence and SHALL not disappear when a quote refreshes. Unknown or inconsistent remaining capacity SHALL prevent positive stake allocation. Day rollover SHALL follow the configured timezone and retain prior history.

#### Scenario: Same scan refreshes repeatedly
- **WHEN** an unchanged event is recommended in successive scans
- **THEN** it consumes one coherent advisory allocation rather than accumulating positions or freeing previously declared commitments

#### Scenario: Two refreshes race for remaining capacity
- **WHEN** simultaneous scans attempt to allocate the last daily slot
- **THEN** serialization or version checking admits at most one active allocation and neither output overstates available capacity

### Requirement: Runtime AI and execution boundaries
Candidate production, probability, ranking, and sizing SHALL be deterministic and complete without AI availability. Optional existing LLM research SHALL remain separate advisory summary/classification/veto evidence with captured sources and provider/model/prompt/output/timing/cost provenance. It SHALL not originate candidates, invent consensus probabilities, size recommendations, alter limits, or bypass any failed gate. Malformed or unavailable AI output SHALL never become an approval; if an explicitly enabled review gate is required, its failure SHALL block that review status. Polymarket paper execution, authenticated trading, and combo creation or synthetic combo pricing SHALL remain outside phases 0-4; the default combo output SHALL be `No combo`.

#### Scenario: LLM recommends a market rejected by the scanner
- **WHEN** optional AI output proposes a new side or larger size
- **THEN** the deterministic candidate and stake remain unchanged and the output has no execution authority

#### Scenario: No AI service is available
- **WHEN** the scanner runs with optional AI disabled or unavailable
- **THEN** deterministic results remain computable and any requested review is visibly unavailable rather than falsely approved

### Requirement: Scanner acceptance and promotion separation
Phase 3 acceptance SHALL require known-answer net-edge/EV and fee tests, deterministic replay, price-band boundaries, depth/minimum-size rejection, zero-result completion, event/daily/third-position caps, concurrent-refresh/day-rollover tests, and proof that no order path is invoked. Scanner release SHALL not constitute a backtest, paper, combo, or live promotion. Future paper work SHALL separately satisfy causal capture, preregistered holdout, calibration, realistic costs/fills, and explicit go/no-go gates owned by the relevant changes.

#### Scenario: Read-only scanner passes all tests
- **WHEN** its acceptance suite succeeds
- **THEN** only the read-only scanner phase is eligible for release and no paper or live execution gate is automatically advanced
