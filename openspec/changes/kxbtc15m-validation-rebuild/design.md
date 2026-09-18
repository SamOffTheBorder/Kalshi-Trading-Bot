## Context

The v2 branch has useful risk controls and strategy scaffolding, but its reported directional results are not valid KXBTC15M evidence. The runner reads multiple series, the current data path supplies hourly spot candles to a short-horizon strategy, and a decision may use a bar's eventual close before being filled within that same bar. Directional decisions do not consistently provide a binary probability, which turns BUY NO decisions into certainty in the backtest path. In addition, NO early-exit accounting and close-leg fees differ from the exchange economics.

KXBTC15M resolves from a published BRTI-based 60-second average, which creates a more direct modelling target than mapping a generic spot return into contract cents. The bot must retain a clear boundary: it is a research and paper-trading plan, and data collection runs only during deliberate operator sessions.

## Goals / Non-Goals

**Goals:**

- Create reproducible, KXBTC15M-scoped evidence that cannot use future information.
- Model an event-contract trade from submitted order through entry and exit costs, including side-aware PnL and partial or unfilled execution.
- Prioritize a calibrated settlement-probability model, with short-horizon trend as a regime/feature subject to the same cost-aware gate.
- Make strategy promotion and perps promotion independently auditable.
- Define an implementation sequence that permits paper trading only after validation gates are met.

**Non-Goals:**

- Authorize live trading, unattended collectors, or a profitability target.
- Assert that any current v2 result, including the funding-carry prototype, is an investable edge.
- Build a universal cross-asset strategy suite, a high-frequency matching-engine simulator, or an AI trade-veto system in this change.

## Decisions

### Make KXBTC15M the single initial instrument

All baseline datasets, reports, and promotion gates will explicitly filter to KXBTC15M. Other event series and perps are held out of the initial evidence set. This prevents a liquid-looking aggregate report from hiding a different instrument mix.

Alternative considered: retain a multi-series universe and report per-series breakdowns. Rejected for the initial rebuild because it makes source-specific semantics, liquidity, and resolution rules too easy to blend before one market is proven.

### Use an as-of event timeline rather than OHLC-bar execution

Features will have an availability timestamp. A decision can consume only snapshots, trades, and benchmark observations at or before that timestamp; an order is eligible to execute only on a later market-data event. Incomplete-candle values and a candle's high/low/close cannot be used to fill an order placed inside that candle. Bar-only history can support only bar-close decisions with execution no earlier than the next bar.

Alternative considered: continue conservative high/low fills in hourly data. Rejected because conservative fill selection does not repair the causal leak and cannot establish short-horizon maker or latency behavior.

### Represent exchange values and trades explicitly

Persist Kalshi fixed-point prices and fractional quantities without cent/integer truncation. A simulated trade records held side, entry and exit order/fill prices, quantities, all matched-order fees, and realized cashflow. YES and NO exits use their own quoted price convention; an early close always incurs the close transaction fee. Resting liquidity remains unfilled unless the dataset proves the fill, or a separately validated queue/partial-fill model supports it.

Alternative considered: infer maker fills from candle ranges and apply a universal maker fee. Rejected because it overstates fill quality, ignores queue priority, and does not reflect market-specific fee schedules.

### Separate prediction from execution and sizing

Strategies emit a timestamped fair probability, direction, confidence, and invalidation conditions. An execution layer compares fair value to side-specific executable prices and full expected friction before deciding to trade. Fixed dollar risk derives size from the actual executable stop distance and costs; Kelly sizing is not used in the baseline. The report derives breakeven from the selected target, stop, entry/exit prices, and both legs' costs, rather than a single global win-rate threshold.

Alternative considered: permit strategies to convert spot percentage moves directly to binary cents and size with Kelly. Rejected because binary delta varies with strike and time to settlement and unstable probabilities magnify Kelly error.

### Prioritize settlement-aware probability; treat trend as conditional evidence

The first candidate model uses the market target, current and final-minute BRTI-window data, time remaining, and a volatility estimate to estimate the probability of settlement. Calibration must be fitted only on prior folds and assessed with Brier/reliability metrics. Short-horizon trend, pullback, microprice, public-trade imbalance, and quarter-hour opening effects enter as candidate features or separately reported experiments. A trend signal cannot trade merely because direction is positive; it must improve out-of-sample net value after execution costs.

Alternative considered: promote the existing hourly z-score trend/pullback strategy. Rejected because its horizon and proxy price are mismatched to a 15-minute binary settlement and it has not produced causal, KXBTC15M-only results.

### Require isolated walk-forward promotion gates

Each train/validation/test fold receives a fresh broker, balance, drawdown guard, and daily guard. Historical observations needed for features may be warmed separately, but outcomes and risk state cannot cross into the test fold. Reports include KXBTC15M trade count, coverage, net PnL/expectancy, calibration, realized versus modeled costs, fill/cancel/partial-fill rates, adverse selection, and block-bootstrap confidence intervals by day. The existing v2 results are retained as diagnostic history but not as promotion evidence.

Alternative considered: a single continuous backtest split into train and test metrics. Rejected because stateful guards can halt or bias the test period.

### Keep perps on an independent safety and economics track

Perp entries, funding, liquidation/margin exposure, and exits are evaluated in a separate ledger and gate. A binary contract is not accepted as a linear funding hedge. Funding carry is disabled unless a compatible linear hedge, its rollover cadence, fees, and residual basis risk are modeled and pass the independent gate. Execution safety uses reconciliation, idempotent client order identifiers, partial-fill handling, anchored reduce-only exit triggers, stale-order cancellation, and confirmation of emergency-close fills.

Alternative considered: use the event-contract strategy's success to release perps or call a binary/perp pair market neutral. Rejected because payoff shape, fee schedule, and risk differ materially.

## Risks / Trade-offs

- [Required streaming data is sparse because collection is manual] → Restrict claims to the data actually present, run deliberate capture sessions, and defer queue/order-flow strategies until sufficient sessions exist.
- [A causality-safe simulation produces far fewer trades or lower returns] → Treat this as a valid negative finding; retain reports and compare only like-for-like folds.
- [Exchange fee or resolution semantics change] → Version the fee/resolution configuration with each run and add a source verification check before promotion runs.
- [Short-horizon observations are autocorrelated] → Use day-blocked/bootstrap uncertainty estimates, embargoed folds, and do not claim independence from raw trade count.
- [More realistic execution models add complexity] → Begin with taker-only executable prices; add maker simulation only after L2/trade data and an independently evaluated model are available.
- [Perps safety work delays feature expansion] → Keep the independent gate; delay is preferable to masking a different risk profile under event-contract results.

## Migration Plan

1. Mark the existing v2 backtest reports as diagnostic and prevent them from satisfying any paper-trading gate.
2. Add precise, timestamped KXBTC15M and BRTI data representations alongside existing records; backfill only data whose provenance and timing are known.
3. Rebuild the simulator and reports behind the new validation path, then run reproducible historical and deliberately captured datasets.
4. Run the settlement-aware baseline and trend-feature experiments through walk-forward evaluation; promote only strategies that meet the defined evidence gate.
5. Enable paper execution in a guarded mode after the event-contract gate passes. Perps remain disabled until their separate gate and reconciliation controls pass.

Rollback is configuration-based: disable the new promotion path and paper execution while preserving raw data and reports for diagnosis. No schema migration shall delete or rewrite historical evidence.

## Open Questions

- Which available historical BRTI source provides sufficiently timestamped data to reproduce the 60-second settlement window, and what gaps require fresh capture?
- What KXBTC15M sample size and minimum calendar coverage will be the promotion threshold after block-bootstrap uncertainty is measured?
- Which current Kalshi API fields expose fee overrides and enough order identifiers to reconcile partial fills and anchored exits in paper mode?
- Does the existing exchange integration support a safe idempotency key, or must the order-state store provide one?
