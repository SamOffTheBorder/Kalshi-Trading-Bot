## ADDED Requirements

### Requirement: Causal source provenance and as-of joins

Each research observation SHALL retain source identity, instrument identity,
source event time, receive time when captured, causal availability time,
capture/reconstruction classification, and schema/version provenance. Feature
assembly SHALL join observations by availability at or before the decision time,
apply frozen staleness and clock-skew tolerances, and preserve missingness.
Historical retrieval time SHALL NOT silently become evidence of historical
real-time availability. Incomplete bars, later revisions, future funding
settlements, and final outcome labels SHALL NOT become earlier decision inputs.

#### Scenario: Source event precedes decision but arrival follows it
- **WHEN** an external trade has an event timestamp before a decision and an availability timestamp after it
- **THEN** the feature set excludes that trade at the decision and records it as eligible only at its availability time

#### Scenario: Historical reconstruction lacks arrival evidence
- **WHEN** reconstructed observations lack reliable original availability times
- **THEN** the manifest identifies their causal limitations and does not classify them as native captured evidence

### Requirement: Candidate-specific qualification matrix

Every candidate revision SHALL define frozen minimum coverage, contiguous usable
windows where required, independent settlement/day counts, sample frequency,
freshness, synchronized overlap, permitted gaps, liquidity/depth, and required
regime coverage. A qualification report SHALL compare measured evidence against
each threshold by asset, instrument, cadence, and source and expose `pass`,
`fail`, or `unknown`, with a specific remaining collection action. Qualification
SHALL use the intersection of eligible inputs rather than the oldest available
source. Time-based targets alone SHALL NOT imply sufficient evidence or an edge.

#### Scenario: Long price history has short book overlap
- **WHEN** a lead/lag candidate has months of spot bars but only hours of causally aligned event-market books
- **THEN** its usable coverage reflects the book overlap and it remains unqualified if the frozen overlap threshold fails

#### Scenario: One asset lacks a required regime
- **WHEN** a candidate's coverage qualifies for BTC but fails the frozen regime coverage requirement for ETH
- **THEN** the qualification report passes only the BTC scope and records the ETH shortfall separately

### Requirement: Prediction settlement and contract-shape data

Prediction datasets SHALL version targets, strike direction, inclusivity at the
boundary, payout rules, settlement index, averaging window, cadence, listing and
close times, final outcome, and corrections. BRTI-dependent candidates SHALL
require native timestamped BRTI observations with the applicable sampling and
averaging rules; exchange spot prices SHALL NOT silently replace that index.
Ladder qualification SHALL verify common settlement semantics, contemporaneous
executable quotes/depth, and the complete legs needed for its payoff claim.
Cross-horizon qualification SHALL retain differences between payoff rules and
settlement windows rather than treating equal underlying assets as compatibility.

#### Scenario: BRTI is missing during a settlement window
- **WHEN** a final-window projection lacks required native BRTI observations
- **THEN** that interval fails its applicable data gate and the report names the missing observations without substituting spot prices

#### Scenario: Thresholds use different settlement conventions
- **WHEN** two candidate ladder legs have incompatible boundary or settlement rules
- **THEN** the system rejects their classification as a compatible ladder and preserves the specific mismatch

### Requirement: Perpetual price funding and risk data

Perpetual datasets SHALL retain executable bid/ask and depth appropriate to the
candidate, trades, mark and reference/index prices, contract multiplier and tick
size, funding estimates as available, realized funding and settlement times,
margin tiers, liquidation rules, fees, and instrument lifecycle changes.
Basis candidates SHALL identify whether the reference is executable or only a
valuation index. Carry candidates SHALL require compatible linear hedge data,
hedge-side execution costs, borrow costs when relevant, rebalance rules, and
residual basis exposure. Relative-strength candidates SHALL require synchronous
eligible data and execution assumptions for every leg.

#### Scenario: Realized funding rate was unknown at entry
- **WHEN** an entry predates publication of the realized funding rate
- **THEN** the signal can use only the then-available estimate and the later realized funding is applied solely at its cashflow time

#### Scenario: Reference index is not a tradable hedge
- **WHEN** a basis test compares an executable perp price with a nontradable index
- **THEN** the report identifies single-leg directional/basis risk and does not report a locked-in two-leg spread return

### Requirement: Microstructure research requires event-level evidence

Lead/lag, order-flow, maker, and executable multi-leg candidates SHALL require
the book/trade events and sequencing needed by their frozen latency and fill
models, including book reconstruction/resynchronization evidence where relevant.
OHLC candles or sparse snapshots SHALL NOT qualify a candidate whose claimed
edge depends on intervening quotes, queue position, sub-snapshot latency, or
unobserved depth. Quote gaps and resynchronization intervals SHALL be explicitly
excluded or handled under a frozen conservative rule with the affected coverage
reported.

#### Scenario: Candle data is offered for a maker strategy
- **WHEN** a maker candidate has candle ranges but no validated queue or observed fill evidence
- **THEN** the data report marks maker execution unqualified and the simulator does not infer filled orders from those ranges

#### Scenario: Book sequence breaks during a lead/lag window
- **WHEN** an event-book sequence gap violates the frozen integrity rule
- **THEN** affected decisions are excluded or conservatively marked unavailable according to that rule and the report quantifies the excluded interval

### Requirement: Immutable datasets and reproducible readiness

Every dataset used for a frozen experiment SHALL have an immutable manifest
containing source snapshots or content hashes, time bounds, eligible and excluded
intervals, transformations, registry/contract versions, qualification policy, and
qualification results. Later backfills or corrections SHALL create a new manifest
version without changing the evidence of completed runs. Research summaries
SHALL show measured numerator and target for each computable readiness percentage
and unknown states for requirements that cannot be measured. Dataset readiness
SHALL remain distinct from strategy validation and collection process health.
Reconstructed data SHALL retain existing paper-fill admission restrictions.

#### Scenario: Backfill arrives after an experiment finishes
- **WHEN** a collector adds missing historical observations
- **THEN** the previous experiment remains linked to its original manifest and any rerun uses a new manifest and experiment revision

#### Scenario: Collection reaches a duration target
- **WHEN** the duration requirement reaches 100 percent but integrity or outcome-count requirements fail
- **THEN** the candidate remains unqualified and the summary shows those failed requirements instead of claiming completed validation

## Model complexity

Complexity is high because causal timestamps, contract rules, and source overlap
can invalidate otherwise plausible results. Use the proposal's stronger-model
allocation for time semantics, reconstruction policy, and qualification design.
Bounded adapters and deterministic fixtures can use its implementation allocation.
Escalate unclear availability, funding, or settlement semantics and any repeated
failure of the same validation scenario.

## Checkpoint

This capability's requirements are written; no capture, dataset, or runtime change
is implemented by this artifact. Continue using the change's CLI status and
design/tasks checkpoint. A replacement model must inspect the frozen provenance
decisions and dependency contracts before changing qualification semantics.
