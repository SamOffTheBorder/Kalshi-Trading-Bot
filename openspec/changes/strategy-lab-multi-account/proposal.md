## Why

The user wants to start testing strategies: a section for perpetuals and for
15-minute scalping, with switchable strategies or several paper accounts
running different strategies concurrently.

Most of what that needs already exists. Seven strategies are written and
unit-tested. `PaperRun` is already keyed by a `uuid4` run id, and every
position, fill, and audit event hangs off `paper_run_id` — so **concurrent
independent paper accounts are already possible at the storage layer**. What
is missing is smaller than it looks, and it is specific.

**No strategy is reachable from the runner.** `scripts/run_paper.py` hardcodes
`strategy=hold_strategy`, a stub returning `no_strategy_configured` on every
tick. Its `--strategy-id` argument is only an audit *label*; it selects
nothing. The multi-venue paper stack therefore cannot trade today, with any
strategy, at all.

**Two paper stacks exist and do not share a strategy seam.** The strategies
implement `StrategyProtocol.evaluate(StrategyContext) -> Decision`, taking a
rich context (spot, vol, trend z-score, OHLCV bars). But
`PredictionPaperAdapter` expects `StrategyFn = Callable[[PredictionQuote],
StrategySignal]` — a bare quote. Nothing in the multi-venue stack assembles a
`StrategyContext`. The older `scripts/run_paper_trading.py` does assemble one,
but is hardwired to `SettlementProbStrategy` and bypasses the orchestrator,
its risk policy, and its admission gates entirely. This fork is the root cause
of the first problem, not a separate inconvenience.

**Perpetuals have no adapter.** `run_paper.py` raises `SystemExit` for
`--domain perp`. The primitives are built and tested — `perp_paper.py` has
fills, funding, brackets, and liquidation; `perp_admission.py` has the gate —
but nothing assembles them into a run loop the way `PredictionPaperAdapter`
does for prediction markets.

### Strategy selection is already decided — and the answer constrains this change

This proposal does **not** need new strategy research. `v2-perps-scalping-and-
frontend` already did it, and re-opening it would repeat work whose conclusions
still hold:

- `strategy-research.md` scored five candidate families against published
  evidence and against this project's own cost floor, and selected exactly
  three: `trend_scalp` (momentum/pullback), `level_break` (breakout, with
  opening-range-breakout folded in), and `funding_carry`. It explicitly ruled
  out order-flow imbalance (the literature itself reports the edge is usually
  smaller than transaction costs) and VWAP reversion (structurally a
  trend-fade, the exact posture Phase 1 already falsified).
- `cost-floor.md` computed the bar each must clear: **50.45% maker-floor,
  52.25% taker-floor** on a 1:1 R round trip near 50¢.

The part that matters most here is what happened next. Tasks 8.1–8.4 ran the
backtests against a pre-registered, never-peeked 2026-08-18 holdout, and
**both directional strategies formally FAILED the gate**:

| Strategy | Train | Test | Gate |
|---|---|---|---|
| `trend_scalp` | 544 trades, 76.5% win vs 66.6% breakeven | **0 trades** | FAIL (≥200 required) |
| `level_break` | 110 trades, 70.9% win vs 67.1% breakeven | **0 trades** | FAIL (≥200 required) |

The failure is not mysterious. §8.3 traced it to a `DrawdownGuard` reentry
circularity: a run that HALTs cannot recover without a new entry's PnL moving
equity, and cannot take a new entry without first recovering. Both strategies
clustered their trades into one early high-drawdown stretch, HALTed, and
produced nothing in the holdout. A genuinely separate Kelly cross-position
sizing bug was found and fixed along the way (drawdown fell 58.1%→46.7% and
50.2%→43.8%), which was real but not sufficient to clear the 40% threshold.

**This is the finding that shapes the proposal.** A "strategy lab" that lets
the operator switch between two strategies which have already failed a
pre-registered gate would be a machine for tuning into a holdout — precisely
the discipline failure §8.3 was built to prevent, and precisely what Phase 1
did wrong (its test window was peeked four times). So this change deliberately
builds the lab as a **paper-trading** instrument, not a backtest-tuning one,
and carries the gate status forward as a visible, mechanical property of every
run rather than a fact buried in a tasks file.

Task 8.5's own ordering says the next candidate after a directional gate
failure is `funding_carry` — never backtested, because it is a two-leg hedge
that does not fit `BacktestEngine`'s single-instrument settle-to-expiry model.
Paper trading is the cheaper way to get first evidence on it, which is a
second reason the perp adapter is in scope here.

## What Changes

- Add a **strategy registry**: one named, versioned mapping from a
  `strategy_id` to a constructed strategy plus its frozen config. `--strategy
  trend_scalp` starts working, and the id recorded in the audit trail becomes
  the same id that selected the behaviour rather than a free-text label.
- Add a **`StrategyContext` builder** inside the prediction adapter so
  `StrategyProtocol` strategies run under the multi-venue orchestrator. This
  closes the fork between the two paper stacks: one strategy object, one
  context contract, backtest and paper alike.
- Add a **`PerpPaperAdapter`** assembling the existing `perp_paper` and
  `perp_admission` primitives into a run loop matching the prediction
  adapter's shape, making `--domain perp` real.
- Add a **multi-account launcher** starting N concurrent paper runs from a
  declarative spec, each with its own strategy, config, assets, and bankroll,
  and each isolated by `paper_run_id`.
- Add **dashboard sections for perpetuals and 15-minute scalping**, with a
  side-by-side comparison view keyed by `paper_run_id`, and per-run controls.
- Carry **gate status onto every run**: a strategy that has failed a
  pre-registered gate, or has never faced one, is labelled as such in the UI
  and in the audit trail. Paper evidence never silently upgrades a strategy's
  standing.

## Impact

- Affected specs: `paper-strategy-execution` (new),
  `perp-paper-execution` (new).
- Affected code: `execution/prediction_adapter.py`,
  `execution/orchestrator.py`, new `strategy/registry.py`, new
  `execution/perp_adapter.py`, `scripts/run_paper.py`, new
  `scripts/run_strategy_lab.py`, `web/app.py`, `web/queries.py`, templates.
- **`PAPER_TRADING=true` remains mandatory.** This change adds no live-order
  path, no scheduler, and no unattended process, consistent with the standing
  decision in `v2-perps-scalping-and-frontend` O1. `PaperExecutionGuard` still
  refuses a production-authenticated configuration during preflight.
- The `reconstructed_data_not_admissible` boundary from
  `brti-constituent-history` is untouched and still binding: a run backed by a
  reconstructed manifest records decisions and refuses fills. Synthetic BRTI
  cannot become paper-trading evidence through this change.
- `DrawdownGuard`'s `allow_reentry_after_halt` stays `False` on every live and
  paper path; it remains backtest-only.

## Open Questions

1. **Does the strategy lab get a backtest mode at all?** Recommendation: no,
   not in this change. The holdout for `trend_scalp`/`level_break` is spent;
   re-running them against it with new configs is tuning into the holdout. New
   backtest evidence for these two should wait for genuinely new data, and
   that is a separate change with its own pre-registered split.
2. **Which strategies are admitted to the registry initially?** Recommendation:
   all seven, each tagged with its real gate status (`gate_failed`,
   `never_gated`, `parked`). Hiding the failed ones would make the lab lie
   about what is known; tagging them keeps the lab honest and still lets the
   operator observe them on live paper data.
3. **Does `funding_carry` need a two-leg `Decision` type?** It does not fit
   `StrategyProtocol` (single-instrument by construction). Recommendation: give
   the perp adapter its own two-leg decision path rather than widening
   `Decision`, matching the existing scope note in `strategy/funding_carry.py`.
4. **What bankroll does each concurrent account start with?** Recommendation:
   per-account, declared in the launcher spec, defaulting to
   `bankroll_total_usd`. Concurrent accounts must not share a capital ledger —
   §8.3's sizing bug was exactly a shared-ledger failure, and the isolation is
   the point of separate accounts.

## Model complexity

| Stage | Recommended | Notes |
|---|---|---|
| Strategy registry + context builder | Opus | The seam between two stacks; getting the causal/look-ahead discipline right in context assembly is the load-bearing part. |
| Perp adapter | Opus | Two-leg coordination, funding, bracket and liquidation interaction. |
| Multi-account launcher | Sonnet | Mostly plumbing over an already-isolating storage model. |
| Dashboard sections | Sonnet | Templates and read-only queries, following existing panels. |
| Tests | Sonnet | Follows the known-answer discipline already established. |

Escalate to Opus if a lighter model produces a context builder that reads any
value at or after `now_ts`, or a launcher that lets two accounts observe each
other's capital.
