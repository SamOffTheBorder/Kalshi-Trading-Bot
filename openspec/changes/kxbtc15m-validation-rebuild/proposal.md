## Why

The v2 backtest results cannot yet support a paper- or live-trading decision: they combine non-KXBTC15M series, use non-causal hourly spot inputs, mis-handle directional and NO-side accounting, and do not model the full cost of a scalp. KXBTC15M remains a promising initial market, but it needs an instrument-specific, causality-safe evidence path before the bot is expanded to perps or additional assets.

## What Changes

- Establish a KXBTC15M-only research and validation path that uses data available at each decision time, correct YES/NO price conventions, both matched legs' fees, and fresh execution/risk state for each out-of-sample fold.
- Add a settlement-aware fair-value strategy based on the contract target, BRTI settlement-window information, time remaining, and calibrated probability; treat trend/momentum, pullbacks, order-flow imbalance, and quarter-hour effects as conditional features or separately gated experiments rather than presumed standalone edges.
- Require validation reports to measure net expectancy, calibration, fill and adverse-selection behavior, and uncertainty under rolling out-of-sample evaluation before a strategy can advance.
- Preserve exact exchange price and quantity precision and collect the market, order-book, trade, and BRTI inputs required to evaluate short-horizon execution strategies. Strategies that need continuous streaming data remain unavailable until deliberately collected data exists.
- Separate perpetual-futures validation and risk from binary-event validation; remove the claim that binary contracts create a market-neutral funding hedge unless a compatible linear hedge and its economics are demonstrated.
- Define production-readiness requirements for reconciled order state, partial fills, anchored reduce-only exits, stale-order handling, and verified emergency closure. Existing v2 performance claims are retired as decision evidence until revalidated.

## Capabilities

### New Capabilities

- `causal-strategy-validation`: Produces instrument-scoped, causality-safe backtests and robust out-of-sample evidence for strategy promotion.
- `settlement-aware-pricing`: Estimates and calibrates KXBTC15M settlement probability from the published settlement methodology and time-indexed market data.
- `perps-strategy-isolation`: Ensures perpetual strategies, funding economics, and execution safety are independently validated from binary-event strategies.

### Modified Capabilities

<!-- No living specifications currently exist in openspec/specs/. -->

## Impact

This affects the backtest broker and engine, strategy interfaces and research runners, Kalshi market-data storage and collection, fixed-risk sizing and reporting, the authenticated execution path, and the operator dashboard's promotion evidence. It uses Kalshi market/order-book/trade APIs and BRTI benchmark feeds; it does not authorize automated live trading or unattended data collection.
