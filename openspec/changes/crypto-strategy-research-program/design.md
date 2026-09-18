## Context

The project has strategy implementations, causal event-market simulation, native BRTI capture,
perpetual mark/funding/book records, an asset registry, and isolated paper ledgers. It does not yet
have a single frozen research program connecting a hypothesis to its required data, experiment
budget, falsification rule, and eventual evidence report. Code existence and unit-test success do
not establish an economic edge.

The binding dependencies are `kxbtc15m-validation-rebuild` (causal execution, settlement pricing,
independent perp gates), `multi-asset-crypto-scalping` (registry, asset/cadence qualification and
correlated exposure), and `strategy-lab-multi-account` (isolated runs and honest gate labels).
Unfinished dependency tasks remain prerequisites; this change does not duplicate their engines.
Manual foreground collection remains the operational policy.

The older `v2-perps-scalping-and-frontend/strategy-research.md` is historical motivation. Its fixed
win-rate floors, binary funding-hedge premise, and strategy rankings cannot override the newer
causal/accounting contracts. Existing failed holdouts remain failed and spent. A new perp momentum
hypothesis is a new experiment, not a relabeling of the failed binary strategy.

Current implementation details that constrain this design:

- `StrategyProtocol` consumes a supplied context; strategy objects do not fetch data.
- `PerpMarkObservation` stores per-contract dollar strings and `contract_size`; comparisons with
  index prices require explicit unit normalization. Settlement/liquidation marks are not fills.
- BRTI, books, trades and funding estimates carry availability/provenance fields. Legacy epoch-second
  storage and coarse polling cannot prove subsecond lead/lag or queue behavior.
- `validation_run.py` currently uses 28 training days, a one-day embargo and 14-day test folds.
  Three test folds need about 71 calendar days before quality exclusions. This is a fold-layout
  minimum, not a guarantee of statistical power or a program-wide completion percentage.
- The current probability recorder covers BUY decisions. Research calibration and model comparison
  need all eligible decision probabilities, including HOLD, to avoid selection bias.

## Goals / Non-Goals

**Goals:**

- Rank a small, economically motivated portfolio that can be tested as its inputs qualify.
- Distinguish diagnostic analysis, development evidence, frozen confirmation, and paper evidence.
- Make every result reproducible and every blocked/rejected idea visible.
- Reuse existing data, simulation, execution and risk seams with asset/instrument isolation.
- Supply dashboard-ready evidence: what the idea means, what data is missing, what ran, what it
  found, and what would qualify it for the next stage.

**Non-Goals:**

- Live orders, automatic allocation/promotion, unattended collectors, or external hedge execution.
- A return target, an assurance that a strategy works, or a date on which enough data must exist.
- A general market-making simulator, a deep-learning model search, or a new execution engine.
- Treating event contracts as linear hedges or pooling assets to rescue a failed promotion gate.

## Decisions

### D1 - Rank hypotheses by plausible mechanism and testability

Priority means research priority, not permission to trade. Incubators stay data-blocked until their
specific gates pass. The initial universe is BTC; ETH is a separately qualified replication after
its registry and dependency gates permit it. Other assets remain observation candidates.

| Rank / ID | Class / candidate | Mechanism and initial experiment | Required evidence and falsification |
|---|---|---|---|
| 1 / E1 | `priority`: settlement-aware probability | Estimate the probability that the published settlement statistic exceeds the target, using distance, time left, native index history and causal volatility; compare a simple calibrated baseline with one trend/volatility feature variant. | Native settlement input, rules and executable event quotes. Kill the variant if calibration and net value fail to improve over the baseline after fees; reject trading if no executable surplus remains. |
| 2 / P1 | `priority`: perp reference-basis convergence | Test whether an unusually wide executable perp/reference gap contracts over a fixed horizon, conditional on trend, spread and liquidity. Compare against naive basis reversion. | Fresh perp bid/ask, reference/index, multiplier, marks, funding and depth. Kill if apparent convergence is stale pricing, directional beta, or smaller than costs. An unhedged trade retains directional risk. |
| 3 / P2 | `priority`: short-horizon momentum/pullback | After a causal trend, test whether a defined pullback/resumption or confirmed level break improves entry economics over simple momentum. Predeclare one pullback variant and one level-break variant. | Fine spot/perp bars plus executable perp quotes and costs. Kill on no incremental net expectancy, reversal-regime losses, or profit concentration in a few episodes. |
| 4 / E2 | `priority`, conditional: final-window projection | During the settlement averaging window, combine the observed contribution with a forecast distribution for the still-unobserved contribution. | Native samples at the contract-required resolution, exact window/rounding rules and contemporaneous quotes. Kill if edge disappears with receipt latency, missing-sample bounds or realistic fills. |
| 5 / E3 | `priority`, conditional: strike-ladder consistency | Test same-statistic/same-expiry thresholds for monotone probabilities and executable payoff dominance; separate a probability feature from a genuinely guaranteed payoff basket. | Simultaneous quotes/depth for compatible strikes and complete payout rules. Kill executable opportunities if fees, legging, depth or nonmatching rules remove the payoff floor. |
| 6 / E4 | `incubator`: external lead/lag and order flow | Test whether external venue innovations or book/trade imbalance add information beyond E1 before Kalshi quotes incorporate it. | Dense source/receipt timestamps, sequenced books/trades and latency distribution. Kill if effect vanishes after availability alignment or costs. Sparse minute data cannot test this claim. |
| 7 / P3 | `incubator`: boundary-flow feature | Add a preregistered quarter-hour/funding/session-boundary indicator to P2 and compare with the identical strategy without it. | Clock-consistent coverage across boundaries, weekdays/weekends and controls. Kill if an apparent effect is merely volatility/liquidity seasonality or fails incremental OOS tests. |
| 8 / P4 | `incubator`: cross-asset relative strength | Test a slow, past-only estimate of BTC/ETH relative exposure and a two-leg residual signal. | Synchronized qualified books, both funding histories, two-leg costs and margin/legging simulation. Kill on unstable hedge ratios, common-market exposure or costs. No pooled asset pass. |
| 9 / E5 | `incubator`: cross-horizon consistency | Compare compatible 15m/hourly/daily probabilities through an explicit joint price/settlement model. | Separately verified targets, observation windows, horizons and liquidity. Kill if conclusions require treating nonidentical events as equivalent or using future settlement labels. |
| 10 / P5 | `incubator`, blocked: linear funding carry | Evaluate realized funding net of a compatible linear hedge, borrow/financing, rebalancing and basis risk. Use funding estimates as P1/P2 cost/regime inputs meanwhile. | A specified executable linear hedge and full two-leg economics. Binary hedges fail classification immediately; absence of a hedge blocks carry rather than silently converting it to directional trading. |
| B1-B4 | `benchmark`: no trade, market-implied event probability, simple momentum, naive basis reversion | Preserve transparent comparators using the same eligibility windows, costs and capital convention as their candidate. | Market-implied probability is a prediction benchmark, not a free executable price; buy-and-hold can be a supplemental directional exposure diagnostic. |
| R1-R5 | `reject`: naive zero-drift mispricing as an edge, unfiltered reversal, candle-range maker fills, binary linear hedges, pooled promotion | Retain their historical diagnoses and explicit reason codes. A zero-drift model may remain a diagnostic pricing comparator only. | No rejected assumption enters promotion evidence. A materially revised hypothesis requires a new version and fresh confirmation data. |

For E2, if a contract specifies N equally weighted samples and n are observed, model the distribution
of `(observed_sum + future_sum) / N`. Never substitute the eventual completed average. If a contract
uses time weighting, trimming, different windows, or tie/rounding rules, use that actual functional.
Unknown rules block evaluation. E2 shares E1's data, so it is economical to develop, but it does not
inherit E1's statistical pass.

For E3, with identical expiry/statistic and K1 < K2, buying YES above K1 and NO above K2 has a
minimum combined settlement payoff of $1 per matched pair when the exact predicates establish
dominance. It is only an executable arbitrage candidate if the full acquisition cost is below that
minimum after all fees and the fill/legging model supports both legs. Merely seeing inverted mids
does not meet that condition. Cross-horizon prices generally have no equivalent monotonic relation.

Alternative considered: expand immediately into many indicators and assets. Rejected because it
magnifies selection bias before data quality and realistic costs are established. Literature can
motivate a slot; it cannot establish this venue's edge.

### D2 - Qualify data for a claim, not by total database rows

Each dataset manifest records source, source-native/reconstructed classification, contract/rule and
fee versions, asset/cadence, units, event time, local receipt/availability time, timestamp precision,
session IDs, missing intervals, clock assumptions, extraction/code hashes and immutable boundaries.
Unsupported timing assumptions downgrade evidence; historical retrieval time must not be rewritten
to pretend a record was captured live. Published historical funding may enter cash accounting at
its documented realization time; a future realized rate never enters a pre-settlement feature.

| Data gate | Qualification needed | Claims blocked when missing |
|---|---|---|
| Q0: identity and economics | Verified registry mapping, active contract, payout/window rules, price/quantity units, fee version and margin/funding convention | Every economic result for the affected instrument |
| Q1: coarse directional research | Completed source-native bars, known availability, no gap spanning the lookback, later executable quote/bar-close-only execution | Intrabar, maker, microstructure and fast lead/lag claims remain blocked |
| Q2: settlement probability | Native index and known resolution labels, target available at decision time, fresh event quotes; reconstructed index clearly diagnostic | E1 confirmation and paper admission |
| Q3: final-window fidelity | Contract-required sample timing/coverage and bounded missing contribution; no interpolated missing settlement samples represented as observed | E2 confirmation; unsupported windows are excluded with counts |
| Q4: executable perp economics | Perp bid/ask/depth, normalized reference and multiplier, settlement/liquidation marks, funding and fee snapshots | P1/P2 economic confirmation; marks alone permit descriptive studies only |
| Q5: microstructure | Sequenced or otherwise integrity-checked books/trades, measured receipt latency/clock error, resolution materially finer than the tested horizon | E4, maker fills and subsecond lead/lag |
| Q6: multiple instruments | Common as-of timeline, compatible payoff metadata, depth/capital for all legs, legging stress and correlated exposure | E3 baskets, E5 consistency claims and P4/P5 portfolio confirmation |

Before inspecting strategy outcomes, freeze each experiment's numerical maximum quote age, sample
spacing, gap tolerance, source skew, minimum usable sessions/markets, minimum depth, spread ceiling
and size assumptions using source constraints and a data-quality-only pilot. There is no universal
one-second threshold: CF Benchmarks currently describes BRTI publication at 200 ms while Kalshi's
perp help page describes one-second index updates. Persist the actual endpoint cadence and the
contract's actual settlement sampling rules instead of conflating these descriptions.

Qualification reports show eligible versus expected windows and exclusions by reason, including
overnight/weekend and volatility coverage. Manual sessions create selection bias; do not describe
session coverage as continuous calendar coverage. Sufficient days with sparse books does not
qualify E4. Readiness is per candidate with explicit missing gates; a percentage summarizes a
checklist and is never a probability of profitability.

Alternative considered: require the same number of days for all candidates. Rejected because
settlement samples, rare dislocations, funding cycles and fast book events need different evidence.

### D3 - Add a frozen experiment layer around existing engines

Use this logical pipeline:

`raw observations -> qualified immutable manifest -> as-of features -> frozen experiment ->`
`isolated causal replay -> cost/risk ledger -> evidence report -> operator research review`.

Add small research records rather than another trading framework:

- **Candidate:** ID/version, rank, mechanism, instrument scope, benchmark, prerequisites,
  falsification rule and lineage to previous rejected versions.
- **ExperimentPlan:** immutable manifest/config/code hashes, decision grid, features/labels,
  calibration method, limited variants, primary endpoint, chronological folds, embargo, execution
  assumptions, hypothesis-family membership, statistical thresholds and stop rule.
- **ResearchRun:** plan ID, engine/environment version, seed, stage, start/end/heartbeat, process
  exit status, data exclusions and output hashes. Running means a verified active run; a proposed
  experiment or old PID is not running.
- **EvidenceReport:** complete metrics, failed gates, uncertainty, benchmark comparison, cost and
  latency stresses, rejected results, exports and the reason for the next state.

Candidate classification (`priority/incubator/benchmark/reject`) is separate from run lifecycle
(`draft`, `data_blocked`, `ready`, `running`, `completed`, `failed`, `cancelled`) and evidence verdict
(`insufficient`, `rejected`, `confirmation_passed`, `paper_review_pending`). These research labels
do not mutate the existing strategy registry's `gate_failed/never_gated/parked` standing or asset
execution modes. An aborted run stays visible; a configuration edit creates a new plan version.

Prediction adapters continue emitting fair probability; execution separately compares side-specific
prices and complete friction. Perp candidates use the existing perp seam and linear cashflow ledger,
not a fabricated YES/NO probability. Features only read values with availability at or before the
decision; fills require a strictly later eligible market event. Equal second timestamps without
sequence information cannot establish within-second order. Feature history can warm a fold, but
positions, balances and risk guards are fresh. Calibration fits only previously available outcomes.

Record predictions on a frozen eligible decision grid for both trades and HOLDs. Compute calibration
on that grid and trade metrics on filled trades; report both populations and prevent frequent
decisions in one contract from masquerading as independent outcomes. Reuse manifest provenance
gates and Strategy Lab run isolation. All qualifying new code paths must have known-answer tests for
future observations, missing samples, side accounting, contract units and fold boundaries.

Alternative considered: put plan state directly into mutable strategy configs. Rejected because
later edits would make earlier results impossible to reproduce and could hide spent holdouts.

### D4 - Use realistic execution and separate forecast value from trade value

Start with taker execution at subsequent observed executable bid/ask, constrained by visible depth
and fixed risk. Event fees use exact applicable schedules and rounding; early exits pay their own
transaction costs. Perps include entry/exit fees on notional, funding, margin/liquidation paths and
gap loss. Future funding estimates are not realized cashflows. Missing prices, stale references,
unverified multipliers and insufficient depth produce explicit no-trade/exclusion reasons.

Maker execution remains unfilled without observed fill evidence or an independently qualified
queue/partial-fill model. A touched candle price proves neither queue priority nor a fill. Multiple
legs pay all fees, may fill at different times, and carry unmatched-leg exposure. Test adverse
selection, partial fills, cancellations, one-leg failure and forced flattening.

Freeze base and adverse execution cases before confirmation. At minimum include higher measured
latency, extra slippage/spread cost, reduced available depth and a funding-sign reversal where
relevant; disclose the exact stress magnitudes. Compute break-even from payoff/risk and both-leg
costs. The older 50.45%/52.25% win-rate examples are not universal promotion thresholds.

Alternative considered: optimize with frictionless mids and add a flat fee afterward. Rejected
because prices, participation, size, funding and fill selection interact with the signal itself.

### D5 - Bound selection and preserve an untouched confirmation period

The first development wave is E1, P1 and P2, with E2/E3 entering only after their data gates pass.
Freeze at most two substantive variants per candidate per wave; ablations and parameter alternatives
count toward that budget. Benchmarks have fixed configurations. Larger searches require a new plan
and are disclosed as additional trials. E1/E2 and P2/P3 share families because their information and
outcomes overlap. Changing asset, cadence, horizon or feature set is a trial, not free replication.

Use chronological walk-forward development with purging of labels/positions crossing a boundary
and an embargo at least as long as the maximum relevant label/holding overlap. Preserve the
existing one-day minimum for the initial 15m event geometry; longer-horizon candidates increase it.
The 28d/1d/14d layout and three folds are an initial BTC event development layout only. Full training
history reuse may follow the existing runner; it does not permit look-ahead outcomes or risk-state
reuse. Random row splits are inadmissible.

Select finalists using development data, then freeze them before a genuinely new chronological
confirmation period begins. Target at least 28 eligible confirmation days as an initial collection
plan, extending by a preregistered sample/power rule when needed; it is not a promise of sufficiency.
Previously inspected data, including the August 18 legacy holdout, can only be development or
diagnostic data. Do not peek and stop when profitable. The scheduled endpoint and extension rule
must depend on time/eligible sample counts, not running PnL. Confirmation results may reject a
candidate; another tuned attempt needs new future confirmation data.

The primary trading endpoint is net expectancy after complete costs on a frozen capital/risk
convention; feature variants also need paired incremental net value over their specified benchmark.
Use session/day-block resampling, clustering repeated decisions by settlement episode and preserving
simultaneous cross-asset dependence. Specify a longer block sensitivity check for persistent
strategies. Report concentration, worst fold/day, drawdown, capital usage, exposure, turnover, fill
quality and baseline/adverse execution results. Probability models additionally report Brier/log
loss and reliability versus the market-implied and simple settlement baselines over all eligible
decisions. A favorable Brier score alone cannot prove tradable edge.

For the finite frozen confirmation batch, use a familywise 5% error budget with Holm correction
across every candidate/asset/cadence primary claim in that batch. All attempted variants remain in
the trial ledger; unsuccessful/aborted results cannot disappear. Secondary metrics are descriptive.
Use valid block-based tests for the declared nulls and disclose sensitivity to block length; if
effective independent observations are inadequate, return `insufficient` rather than a pass. Future
research waves cannot reuse the same confirmation sample and restart the error budget.

A confirmation pass requires all inherited applicable promotion gates plus adequate preregistered
power/sample coverage, positive uncertainty-adjusted net expectancy, the registered incremental
test where required, cost-stress tolerance and acceptable concentration/drawdown. The current
30-trade/three-fold policy is a lower engineering bound, not a substitute for these checks. Any
missing uncertainty metric fails closed. Event and perp passes remain independent; aggregate
portfolio metrics never override an asset/cadence failure. Reports nominate research finalists for
operator review; they do not activate paper or live execution.

Alternative considered: select the largest Sharpe ratio from all runs and use one ordinary p-value.
Rejected because repeated variants, correlated outcomes and inspected holdouts invalidate that
interpretation. A small preregistered portfolio is easier to audit than a large corrected search.

### D6 - Make reports useful in the existing dashboard

Export immutable JSON plus human-readable Markdown/HTML summaries and tabular prediction, fill,
funding, cost and exclusion records, linked by plan/run ID. Include hashes and a reproduction
command/config; redact credentials and account identifiers. Large raw captures remain referenced
by manifest rather than embedded in every report.

Dashboard-ready cards include: plain-language mechanism; priority and evidence state; data needed
versus qualified; latest run status/time; exact blockers; benchmark comparison; net versus gross
results; uncertainty; stress results; and next action. Show failed, cancelled and rejected runs next
to successful ones. Software test status, capture status, research completion and economic evidence
are separate fields. This change provides the report contract; it does not independently launch
capture, add a second process manager, or broaden Strategy Lab permissions.

Alternative considered: a single overall green/red readiness score. Rejected because it hides the
difference between fully implemented software and an unproven strategy.

## Risks / Trade-offs

- [The cleanest strategy has no net edge] -> Preserve the negative result; avoid broadening search
  after reading confirmation outcomes.
- [Manual sessions miss adverse regimes] -> Disclose session selection and require the declared
  regime/calendar coverage; do not extrapolate to uncaptured hours.
- [Fine timestamps imply precision unsupported by the feed] -> Retain original precision and
  measured clock/receipt uncertainty; block fast claims when ordering is ambiguous.
- [A forecast becomes more certain near expiry but untradeable] -> Require later available liquidity,
  fill delay and expiry buffers in E2; certainty of a forecast is not an executable price.
- [Exchange/index methodology changes] -> Version source documents and instrument metadata per run;
  split incompatible eras instead of silently pooling them.
- [Many correlated tests create a winner by chance] -> Small trial budget, immutable trial ledger,
  blocked uncertainty and frozen multiplicity correction.
- [Multi-leg apparent arbitrage leaves an unhedged position] -> Depth/capital constraints and explicit
  legging failure/flattening stresses; no atomic-fill assumption.
- [Added research records duplicate Strategy Lab state] -> Store references to existing run and
  manifest identities; research state never authorizes execution.

## Migration Plan

1. **Freeze the program now:** create candidate cards, inherited dependency checks and experiment
   schemas; retain legacy results with their original diagnostic/failed status. No collector starts.
2. **Qualify capture:** produce Q0-Q6 coverage reports from deliberate sessions; audit units,
   timestamps, provenance and sampling before outcome analysis. Add only missing adapters needed
   by the first wave, with inherited data contracts.
3. **Build reproducible development runs:** connect E1/P1/P2 to existing engines; add all-decision
   recording and realistic costs; prove causality/accounting on known-answer fixtures. Run bounded
   development experiments when data qualifies. Add E2/E3 only at their respective gates.
4. **Freeze and confirm finalists:** reserve new future data, execute the registered statistical and
   stress protocol, and publish both passing and rejected reports. Incubators remain separately
   blocked rather than delaying every candidate.
5. **Hand off qualified evidence:** provide report links and the exact outstanding dependency/paper
   gates for a later operator decision. This proposal never changes execution lifecycle modes.

Future schema work must be additive/idempotent, tested against populated SQLite databases and
backed up before migration. Roll back by disabling new research registrations/report routes and
stopping only their manually launched research jobs. Preserve raw observations, immutable plans,
trial history and outputs; never erase unfavorable results or downgrade existing protections.

## Sources and Evidence Boundaries

Sources checked September 15, 2026. Reverify operative documents at experiment freeze; these links
are mechanism/contract references, not evidence of this bot's profitability.

- [Kalshi CRYPTOSHORT filing](https://www.cftc.gov/filings/ptc/ptc03112640675.pdf): configurable
  settlement statistic, lookback and predicates; the actual market rules must instantiate them.
- [CF Benchmarks BRTI](https://www.cfbenchmarks.com/data/indices/BRTI) and
  [methodology](https://docs.cfbenchmarks.com/CME%20CF%20Real%20Time%20Indices%20Methodology.pdf):
  index definition and publication methodology, not permission to reconstruct native observations.
- [Kalshi orderbook API](https://docs.kalshi.com/api-reference/market/get-market-orderbook) and
  [orderbook conventions](https://docs.kalshi.com/getting_started/orderbook_responses): binary bid
  representation and complementary-side ask conversion.
- [Kalshi perp specifications](https://help.kalshi.com/en/articles/15357587-btc-perpetual-futures-contract-specifications),
  [funding](https://help.kalshi.com/en/articles/15357613-how-funding-works), and
  [fees](https://help.kalshi.com/en/articles/16071417-perps-fees-explained): linear contract units,
  scheduled funding, and notional-based entry/exit fees. Preserve actual current contract settings.
- [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888): economic motivation for
  studying basis/funding; not a guarantee of a readily captured arbitrage.
- [On the intraday return curves of Bitcoin](https://centaur.reading.ac.uk/97607/): motivation for
  investigating conditional intraday predictability; findings require independent venue-specific,
  cost-aware replication.

## Open Questions

- Which feed and storage precision actually qualify final-window and lead/lag experiments? Resolve
  with the data-only capture audit; do not infer qualification from published feed speed.
- What numerical age/gap/depth thresholds and minimum detectable net edge are supportable at the
  intended trade size? Freeze them before outcomes are inspected; missing values block confirmation.
- Can the available perp data reconstruct liquidation exposure and executable depth throughout
  gaps? Until proven, affected analyses remain diagnostic.
- Which specific linear hedge could eventually qualify P5, and what financing/access costs apply?
  It remains blocked until a separate concrete hedge design exists.
- When will enough independent sessions/regimes exist for the intended confidence bounds? The
  manifest and power analysis answer this; a calendar target alone cannot.

## Model complexity

Complexity remains **high** because timestamp semantics, settlement functions, execution costs,
multiple testing and dependencies interact. Use GPT-6 Astra at high/xhigh effort, or advisory
Claude Opus 5, for this design, requirements, causal/economic review and final evidence acceptance.
GPT-5.6 Terra or advisory Claude Sonnet 5 can implement bounded adapters, deterministic reports,
fixtures and dashboard presentation after contracts are frozen. Lighter models may handle mechanical
formatting only; they must not change rules, timestamps, hedge classification or promotion policy.
Escalate for unclear instrument semantics, new fill assumptions, split/holdout changes, or two
failures of the same validation scenario. Anthropic recommendations do not claim execution in an
Anthropic session. No model choice changes the scientific evidence gate.

## Checkpoint

`crypto-strategy-research-program/design.md` is complete as a planning artifact; no application
code, data collection, backtest, or trading process was started by this artifact. Design dependencies
and the CLI design contract were read; operative primary references above were checked. The parent
proposal workflow must review alignment with the new capability specs, generate the tasks artifact
after both design and specs are done, and run OpenSpec validation. Current design work uses the
available GPT-6 session; advisory model allocations are recorded above.

A replacement model must run `openspec status --change crypto-strategy-research-program --json`,
read this design, its proposal, the generated capability specs and the named dependency artifacts,
then request CLI instructions for the next ready artifact. Do not regenerate this design solely
because the model changed. Escalation triggers and unresolved data decisions are listed above.
