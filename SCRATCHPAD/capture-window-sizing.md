# KXBTC15M capture-window sizing

Recommendation: capture **90 consecutive UTC days** of KXBTC15M markets and
BRTI readings at a **1-minute cadence** (or every available quote/readings
update, with no intentional gaps). Keep the 15-minute event boundaries and
settlement metadata; do not downsample BRTI or event quotes to one row per
event. Starting 2026-09-06, this gives a planned first complete report around
2026-12-05.

## Why 90 days

The promotion policy requires at least 30 trades, three test folds, positive
day-block bootstrap expectancy CIs in every fold, and Brier <= 0.25. The
strategy does not trade all approximately 96 KXBTC15M events/day, so the event
count alone is not an evidence count.

Use this conservative rolling layout:

| segment | duration |
| --- | ---: |
| training window | 28 days |
| embargo | 1 day |
| test fold 1 | 14 days |
| test fold 2 | 14 days |
| test fold 3 | 14 days |
| reserve for gaps/restarts | 19 days |

The minimum contiguous geometry for three 14-day test folds is about 71 days
(28 + 1 + 14 + 14 + 14). Thus the first geometrically non-vacuous verdict is
approximately **2026-11-16**, but 90 days is the recommended operator target:
it leaves room for outages, day-block bootstrap resampling, and the strategy's
hold filters.

At an assumed eligible trade rate of 1% of events, the estimate is:

`96 events/day × 1% × 90 days ≈ 86 trades total`, or about 29 trades per
14-day test fold. This clears the 30-trade total threshold with useful margin.
At 0.5%, the same capture produces about 43 trades (14 per fold); at 0.25%,
about 22 trades and cannot clear the policy. The run should therefore stop only
after both the time target and the observed trade-count/fold thresholds are
met; more calendar time cannot repair a structurally inactive strategy unless
the cause is an outage or data gap.

## Cadence and collection contract

- Record every KXBTC15M market's open/close/settlement/result and one-minute
  candles or quote snapshots through its lifecycle.
- Record causal BRTI observations with observed and available timestamps at
  least once per minute. A missing interval must be reported, not forward-filled
  as if observed.
- Keep one capture session ID per foreground collection session and retain
  restart/resume evidence.
- Do not add alternate series, tune thresholds, or substitute another spot
  feed to increase the count. Those changes make the verdict a different
  experiment.

## What breaks the estimate

The 90-day estimate is not a guarantee of statistical significance. It breaks
or becomes non-comparable when quote/BRTI outages remove causal observations,
fills are materially below eligible signals, trades cluster on only a few days,
the realized fee/slippage distribution differs from the modeled cost, or a
fold's bootstrap CI still crosses zero. A completed window may therefore still
produce a valid **NO-GO**. Re-run with the same frozen configuration after
repairing data capture; do not pool folds or assets to bypass a failing fold.
