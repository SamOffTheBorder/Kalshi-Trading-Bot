## Why

The BTC directional strategies have failed their pre-declared out-of-sample
gate, so further tuning would be unjustified. Kalshi now lists liquid sports
markets with structured event and game-state information, making sports a
plausible—but unproven—alternative research track.

This change establishes a reproducible, execution-realistic feasibility study
before the project commits to a sports strategy, paper trades sports markets,
or exposes live capital.

## What Changes

- Discover and screen Kalshi sports series and markets by sport, contract
  shape, settlement rules, time to event, liquidity, spread, and depth.
- Capture point-in-time sports market data and rule provenance through
  operator-run, read-only collection; no unattended collector is introduced.
- Build a sports feasibility evaluator that compares calibrated candidate
  probabilities against the contemporaneous Kalshi market, then scores only
  realistic, fee- and fill-adjusted opportunities.
- Define a narrow first pilot: two-outcome, single-game markets only. Futures,
  player props, combos/parlays, and live capital are explicitly out of scope.
- Require a pre-registered holdout, market-price benchmark, calibration,
  executable-size analysis, and paper-trading gate before any later sports
  execution proposal.

## Capabilities

### New Capabilities

- `sports-market-discovery`: identify and persist the eligibility, liquidity,
  rules, and settlement metadata of Kalshi sports markets.
- `sports-market-data`: collect auditable point-in-time sports contract data
  and market-rule provenance through foreground, read-only operator sessions.
- `sports-feasibility-validation`: evaluate candidate sports signals against
  market probabilities with causal data, realistic execution costs, and a
  fixed promotion-or-park gate.

### Modified Capabilities

None.

## Impact

- Affected code: new sports discovery/data/validation modules, additive storage
  records, a foreground capture command, and feasibility-report scripts.
- Kalshi public market-data endpoints are the required initial integration.
  Any independent odds, injury, lineup, or live-play provider remains optional
  and requires a separately approved source and terms review.
- No production orders, paper orders, new paid provider, or new background
  process is introduced by this change.
