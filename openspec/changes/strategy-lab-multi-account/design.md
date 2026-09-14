# Design: strategy lab and multiple paper accounts

## Context

The request is operator-facing: a section for perpetuals and one for
15-minute scalping, with switchable strategies or several concurrent paper
accounts. The engineering underneath is narrower than the request sounds,
because the storage model already isolates runs by `paper_run_id` and seven
strategies already exist and pass unit tests.

What does not exist is a path from a strategy id to a running strategy, a
perp run loop, and a UI to start and compare runs.

## Terminology note

Everything in this codebase targets **KXBTC15M — 15-minute** contracts: the
settlement rule, the 60-second averaging windows, and `BRTI_HISTORY_MAX`
sized for "several 15-minute contract lifetimes." The user's phrasing was
"15-hour scalping." This design assumes 15-**minute** throughout. If a
15-hour horizon is genuinely wanted, it is a different contract series with
different settlement mechanics and is out of scope here.

## Decisions

### D1: One strategy seam, not two

`StrategyProtocol.evaluate(StrategyContext) -> Decision` wins;
`StrategyFn = Callable[[PredictionQuote], StrategySignal]` is adapted onto it
rather than the reverse.

The `StrategyFn` seam was introduced deliberately in
`multi-venue-paper-trading` "while the change's strategy selection is still
open" — its own comment says so. Selection is no longer open, and the
protocol form is the one the backtest engine, the walk-forward harness, and
all seven strategies already speak. Keeping both would preserve the fork that
is the root cause of the runner being unable to trade.

The existing `StrategyFn` type stays as a thin adaptor for the sports domain,
which has its own `SportsStrategyFn` and a genuinely different market shape.

### D2: Context assembly lives in the adapter, and is causal by construction

The adapter builds `StrategyContext` because it is the only layer holding both
the session and the quote source. The look-ahead discipline is the load-bearing
part: `BacktestEngine` already established the pattern (`_load_spot_bars` /
`_bars_before`), and the paper adapter must match it, filtering on
`available_at <= now_ts` rather than `observed_at`.

Where an input is missing, the context field is left unset and the strategy
decides. The adapter never substitutes a default — §8.3 found that an empty
`spot_bars` silently blocked two strategies for an entire era of data, and
that failure was only diagnosable because the emptiness was honest rather than
papered over with a forward fill.

### D3: The lab is a paper instrument, not a backtest tuner

This is the most consequential decision in the change, and it is a
restriction rather than a feature.

`trend_scalp` and `level_break` have already failed a pre-registered gate
against a never-peeked 2026-08-18 holdout — zero test-segment trades each,
against a ≥200-trade criterion. That holdout is spent. A lab offering "switch
strategy, re-run backtest, compare" against that same data is a machine for
tuning into a holdout, which is exactly the discipline failure that made Phase
1's results untrustworthy (its test window was peeked four times).

So the lab runs **forward, on live paper data**, where every observation is
genuinely out-of-sample because it did not exist when the config was frozen.
Backtest re-runs for these two strategies wait for new data and a new
pre-registered split, in a separate change.

### D4: Gate status is a property of the strategy, carried onto the run

Each registry entry declares `passed` | `gate_failed` | `never_gated` |
`parked`, and no paper result mutates it.

The alternative — hiding gate-failed strategies from the lab — was rejected.
The operator has a legitimate reason to watch a gate-failed strategy on live
paper data: §8.3's diagnosis was that the failure came from dataset clustering
interacting with a `DrawdownGuard` circularity, not from a demonstrated
absence of edge. Forward paper data is a fair way to gather more evidence.
What must not happen is that evidence quietly changing the strategy's
standing, so the label rides along and the promotion path stays where it is.

Initial statuses, from `v2-perps-scalping-and-frontend` §8:

| Strategy | Status | Basis |
|---|---|---|
| `trend_scalp` | `gate_failed` | 0 test trades vs ≥200 (8.4) |
| `level_break` | `gate_failed` | 0 test trades vs ≥200 (8.4) |
| `funding_carry` | `never_gated` | Never backtested; doesn't fit the engine (8.5) |
| `settlement_prob` | `never_gated` | Built in `kxbtc15m-validation-rebuild`, data-blocked |
| `short_horizon_trend` | `never_gated` | Same; explicitly "NOT presumed to be an edge" |
| `crypto_mispricing` | `parked` | Proposal "Removed Capabilities" — no demonstrated edge |
| `hold` | `never_gated` | The default; never enters |

### D5: Accounts are isolated down to the capital ledger

Each concurrent run gets its own bankroll, declared per-account in the
launcher spec. Sizing for one run never observes another's cash, positions, or
equity.

This is not merely tidy. §8.3's second sizing bug was precisely a shared-ledger
failure: concurrent correlated entries each read the same pre-batch equity, so
each believed the whole bankroll was available, producing a phantom 57.7%
drawdown. Separate accounts that shared capital would reproduce that bug at a
larger granularity, and the isolation is the entire point of having separate
accounts at all.

### D6: The perp adapter owns two-leg decisions

`funding_carry` spans a perp leg and an event-contract hedge leg, and its own
module scope note already records that it "does not fit `StrategyProtocol`."

Widening `Decision` to carry a second leg would push two-instrument
complexity into a type that every single-instrument strategy and the whole
backtest engine depend on. The adapter takes it instead, and `Decision` stays
single-instrument.

The carry result is measured as net funding collected after both legs' fees,
not as a win rate — `funding_carry.py` already found that a $10,000 notional
hedged at 50¢ carries roughly $350 of fee drag on the hedge leg alone,
needing funding north of 3.5% just to break even there. The adapter records
both legs' costs so this is readable directly rather than inferred.

## Risks

**The lab makes it easy to run strategies that have failed a gate.** Mitigated
by D4's labelling, and by the fact that paper results cannot alter gate status.
The residual risk is psychological rather than mechanical: an operator watching
a labelled `gate_failed` strategy make paper money may want to promote it. The
promotion gate is unchanged and still refuses.

**Concurrent runs multiply API load.** Each prediction run polls Kalshi's
public `/markets`; each perp run polls authenticated `/margin` read endpoints.
The launcher needs a documented per-run poll interval and a bounded account
count, or N accounts become N times the rate-limit pressure. Kalshi's 429
backoff already exists and is exercised; this is a matter of not defeating it.

**KXBTC15M paper data is still thin for settlement-aware strategies.** The
standing data blocker applies: `settlement_prob` and `short_horizon_trend`
need captured BRTI, and synthetic BRTI cannot substitute — the
`reconstructed_data_not_admissible` boundary refuses fills. Those two
strategies will record decisions and not fill until real BRTI capture
accumulates. That is correct behaviour, and it should be visible in the UI
rather than looking like a bug.

## Open questions

Carried in `proposal.md`. The two that most affect implementation shape are
whether the lab gets a backtest mode (recommended: no, per D3) and whether
`funding_carry` widens `Decision` (recommended: no, per D6).
