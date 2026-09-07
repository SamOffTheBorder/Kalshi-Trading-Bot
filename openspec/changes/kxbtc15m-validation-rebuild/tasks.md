## 1. Evidence Baseline and Data Contract

- [x] 1.1 Mark existing v2 reports as diagnostic only and add a KXBTC15M-only run configuration with dataset provenance. Added evidence classification/provenance columns and `--kxbtc15m-only`; fingerprints include rows, range, config versions, and git context. 2 new tests; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.2 Audit Kalshi fixed-point field handling and migrate persisted prices and quantities to retain exchange precision without rewriting historical rows. Parser now uses Decimal for legacy cents and retains exact nullable `*_dollars`/`*_fp` values; versioned additive migration covers populated and fresh SQLite. 2 migration/precision tests; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.3 Define timestamp/availability metadata for Kalshi market, order-book, public-trade, BRTI, and candle observations. Added `observed_at`/`available_at` plus capture provenance and documented canonical names for all five observation types. 1 schema test; 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.4 Implement deliberate-session capture and import paths for the required KXBTC15M, BRTI, L2, and trade data, including gap/provenance reporting. Added foreground-only `scripts/capture_session.py`, conservative 8/s Kalshi capture, timestamped JSONL imports, session tagging, and per-kind gap/session reports. 338 non-backtest tests passed; ruff + pyright clean.
- [x] 1.5 Version the market-resolution and fee configuration used by each validation run and add tests against documented fee and resolution examples. Added versioned `FeeConfig`/`ResolutionSpec`, run columns, and hand-worked 42c × 11 taker fee plus tie/direction resolution tests. 2 example tests; 338 non-backtest tests passed; ruff + pyright clean.

## 2. Causal Backtest and Execution Accounting

- [x] 2.1 Refactor the backtest timeline so features use only as-of observations and orders
      execute only on later eligible events.

      **Done.** `BacktestEngine` gained a deferred-order queue (`PendingEntry`). The
      evaluate step no longer sizes/fills inline — a decision that would enter is QUEUED,
      keyed by market (at most one pending order per market; a market with an order in
      flight is not re-evaluated). A new step 3 in the main loop, running AFTER settlement
      and BEFORE the equity/guard mark, drains pending entries: for each market with a
      pending order and a candle at the current timestep, `_execute_pending()` runs the
      full gate/size/fill/record path against THAT candle. Every gate is now evaluated at
      FILL time against fill-time state — guard (`allows_new_entries()` at the fill ts),
      throttle, liveness (`is_live_quote` on the FILL candle), bankroll re-mark + sizing,
      and the entry-band check against the ACTUAL fill price. The feature-side as-of
      discipline (spot/vol/trend-z/spot_bars all strictly-before `ts`) was already correct
      and is unchanged. The decision's `SignalRecord` is captured into the `PendingEntry`
      and its `.id` read after a flush at fill time (the row isn't flushed at decision
      time), so the `SimulatedTrade.signal_id` FK still links correctly. A queued entry
      whose market closes before any next candle arrives — or that is still queued when
      history ends — expires unfilled and is counted (`pending_expired` in the run summary
      log). No BrokerAdapter or strategy change; the paper/live loop is unaffected (it
      already decides-then-submits across real book updates — this makes the backtest match
      that).

- [x] 2.2 Restrict bar-only datasets to next-bar-or-later execution and add regression
      tests that detect look-ahead through incomplete OHLC bars.

      **Done as the direct consequence of 2.1's queue.** A decision made from the candle
      ending at `ts` can only fill against a candle ending at `ts' > ts` for the same
      market — the engine never fills an order inside the same bar whose close the decision
      consumed, and a bar's high/low/close can no longer fill an order "placed" during that
      bar. New `tests/backtest/test_engine_causal_timeline.py` (6 look-ahead regression
      tests, each built so the OLD same-bar and NEW next-bar behaviour give visibly
      different hand-checked results):
        1. a single candle → decision queued, never fills (old engine filled it against
           that very bar);
        2. decision-bar `ask_high` 42c but next-bar `ask_high` 60c → fill pays **60c**, the
           pessimistic price of the bar it actually executed in, not 42c (the exact leak
           this task closes);
        3. a gap between decision bar and next candle → order waits, fills on the first
           later candle that exists;
        4. market closes before any next candle → queued order expires, no phantom
           settlement entry, no error;
        5. decision bar live, fill bar dead (0 OI shell) → dropped by the fill-time
           liveness gate, and not rescued by a later healthy candle (strategy fired once);
        6. guard HALTED at the fill timestep → queued entry decided while NORMAL does not
           execute.
      The four existing engine tests that had encoded same-bar decide-and-fill
      (`test_engine_known_answer`, `_directional_probability`, `_concurrent_sizing`,
      `_fixed_r_exit`) were updated to seed a second candle per market at the next
      timestep; where the fixtures were hand-computed (`known_answer`, `fixed_r_exit`) the
      fill candle carries identical prices, so every hand-checked number is unchanged and
      only the fill *timestep* moves one bar. `concurrent_sizing`'s shared-shrinking-
      bankroll property is preserved — a correlated batch still all decides on one bar and
      all drains on the next (single fill timestep); the deferral does not spread a batch
      across bars. Full suite: 377 passed, ruff + pyright clean.
- [x] 2.3 Correct directional decision contracts so BUY YES and BUY NO both carry a valid, side-consistent fair probability and no default certainty path exists.
- [x] 2.4 Rebuild simulated YES/NO lifecycle accounting with explicit entry/exit cashflows, fees on each matched leg, fractional quantity support, and side-aware early exits.
- [x] 2.5 Implement taker-only executable pricing as the initial execution model; record resting orders as unfilled until a validated queue/partial-fill model is introduced.
- [x] 2.6 Add unit and scenario tests for NO-side gains, early-close double-leg fees,
      unfilled maker orders, timestamp causality, and precision retention.

      **Done, spread across the layer each concern belongs to:**
      - **Broker unit level** (`tests/unit/test_backtest_broker.py`, from §2.4/§2.5):
        NO-side gain/loss (`test_close_position_early_no_side_gain_uses_no_exit_value`,
        `_loss_when_no_price_falls`), early-close double-leg fee
        (`_charges_exit_leg_fee`, `test_settle_market_hold_to_expiry_has_no_exit_fee`),
        unfilled maker order (`test_maker_order_is_unfilled_even_when_candle_range_would_
        touch_it`, `_rejected_before_limit_price_check`, `test_taker_is_the_only_fill_path`).
      - **Engine scenario level** — new `tests/backtest/test_engine_scenario_accounting.py`
        (5 tests): a BUY_NO settling NO is a win with entry-fee-only accounting on the
        persisted `SimulatedTrade` row (`entry_fee_usd`/`exit_fee_usd`/`fee_usd`/
        `net_pnl_usd` all hand-checked against `entry_fee_dollars`); its mirror (settles
        YES → loss); a fixed-R **target** exit records BOTH leg fees with
        `fee_usd == entry+exit` and `net == gross - entry_fee - exit_fee`; the same for a
        fixed-R **stop** exit at a loss; and the contrast case — a hold-to-expiry
        settlement has `exit_fee_usd == 0`.
      - **Timestamp causality** — covered by §2.2's new
        `tests/backtest/test_engine_causal_timeline.py` (6 tests): no same-bar fill, fill
        pays the next bar's price not the decision bar's, first-later-candle fill after a
        gap, queued order expires if the market closes first, and both liveness and the
        drawdown guard are evaluated at fill time.
      - **Precision retention** — the exchange `*_dollars`/`*_fp` columns and their
        no-truncation guarantee are §1.2's; tests live with the data-contract layer, not
        the engine. The engine deals in the integer-cents fill prices those columns
        preserve alongside.
      - **Maker at the engine level** — not applicable: `BacktestEngine` never submits
        `execution_style="maker"` (there is no strategy path that produces one), so the
        maker-unfilled contract is a broker-unit concern only.
      Full suite: 382 passed, ruff + pyright clean.

## 3. Risk, Walk-Forward, and Reporting Gates

- [x] 3.1 Make fixed dollar risk derive from executable stop distance and full expected costs; remove baseline Kelly sizing from the validation path. Added `FixedRiskConfig` and `size_validation_position`; Kelly remains available only to legacy/live-compatible callers and is not imported by the validation primitives.
- [x] 3.2 Compute per-trade breakeven and expectancy from actual entry, stop, target, fill assumptions, and both-leg costs. Added `TradeEconomics`/`trade_economics` with held-side prices and separate entry/stop/target fee legs.
- [x] 3.3 Implement embargoed rolling walk-forward evaluation with fresh broker, cash, and risk-guard state for every out-of-sample fold. Added `rolling_folds`, `WalkForwardFold`, `run_walkforward`, and a boundary-plan CLI; evaluator factories are invoked once per fold.
- [x] 3.4 Produce per-fold and aggregate reports for net expectancy, coverage, calibration/Brier score, realized versus modeled costs, fills, cancels, partial fills, and adverse selection. Added typed `FoldReport`/`AggregateReport` builders over settlement and optional execution/prediction observations.
- [x] 3.5 Add day-blocked bootstrap confidence intervals and parameter-stability/latency-outage sensitivity checks to the promotion report. Added deterministic day-block bootstrap plus stability and outage summary helpers.
- [x] 3.6 Define and enforce the paper-trading promotion gate; preserve failed and legacy results without treating them as passing evidence. Added explicit validation-evidence, sample, coverage, expectancy, Brier, fold-CI, and status checks; legacy/diagnostic reports cannot pass.

## 4. Settlement-Aware and Trend Research

- [x] 4.1 Implement KXBTC15M target and settlement-window feature construction from
      timestamped BRTI observations and time remaining.

      **Done.** New `src/kalshi_bot/signals/settlement_window.py` — storage-free and
      strategy-free (same decoupling as `strategy/levels.py`), so it is unit-testable
      with synthetic BRTI series and carries no ORM/protocol dependency.
      - `BRTIReading(observed_at, value, available_at)` — `available_at` is the §1.3
        causal stamp (when a live system could first act on the value); `usable_at`
        falls back to `observed_at` when it is absent.
      - `window_average(readings, end_ts, window_seconds=60, now_ts=None)` — mean BRTI
        over `(end_ts - window_seconds, end_ts]`, the exact averaging the published
        `ResolutionSpec` (`2026-09-kxbtc15m-brti-60s`) uses at both open and close.
        `now_ts` additionally drops readings not yet usable, so a caller can ask for the
        *close* average from what is known so far (usually None until the window is
        nearly over — the correct "outcome still open" signal).
      - `build_features(...) -> SettlementWindowFeatures`: `reference_avg` (the FIXED
        60 s open-window average — the level the close average must beat for YES),
        `current_avg` / `last_value`, `seconds_remaining`, `fraction_elapsed`,
        `drift_so_far` (= current − reference; positive favours YES), and
        `realized_vol_per_sec` (std of 1-second-scaled BRTI log returns this window).
        Consults only readings usable at/<= `now_ts`.
      - `settlement_probability(features, vol_per_sec=None, drift_per_sec=0.0)`: the
        BASELINE P(Δ >= 0) model — a Brownian-bridge-style approximation,
        `Phi((drift_so_far + drift_per_sec·T) / (level·sigma_1s·sqrt(T)))`, tie-goes-to-
        YES already satisfied by the `>=` boundary. Returns None when even this
        baseline's inputs are missing (unknown drift, no vol estimate) — the strategy
        must HOLD, never guess; returns exactly 1.0/0.0 at `seconds_remaining == 0`.
        This is the number §4.4's trend features have to beat out-of-sample.
      13 known-answer unit tests (`tests/unit/test_settlement_window.py`): trailing-60 s
      mean, interval exclusion, `now_ts` usability cutoff, fixed reference average,
      `drift_so_far` arithmetic, future-reading exclusion, missing-open-window → None,
      the Phi(0)=0.5 symmetric case, a hand-computed normal-CDF value, the determined
      zero-seconds case, and the no-volatility → None guard. Full suite 395 passed,
      ruff + pyright clean, no new dependencies (`scipy.stats.norm` already in use).
- [x] 4.2 Build a train-fold-only calibrated probability baseline and persist
      model/version/input metadata with each estimate.

      **Done.** New `src/kalshi_bot/strategy/settlement_prob.py`:
      - `Calibrator` protocol (`.version`, `.calibrate(raw_p) -> float`), an
        `IdentityCalibrator` (default no-op), and an `IsotonicCalibrator` fitted by the
        pool-adjacent-violators algorithm on `(raw_probability, realized_outcome)` pairs.
        It groups by raw probability first (sorting on x only — never tie-breaking on the
        outcome, which would hand PAV an already-monotone 0s-then-1s block and defeat the
        pooling), then pools. Monotone by construction, so it can only correct the LEVEL,
        never re-order the model's ranking; linear-interpolated between knots, clamped to
        the fitted range outside it. `IsotonicCalibrator.fit(...)` returns an
        `IdentityCalibrator` (still a valid `Calibrator`) when given < 10 points.
      - **Train-fold-only by construction**: the strategy takes an injected `calibrator`
        (default identity); the §3.3 walk-forward harness fits the isotonic calibrator on
        PRIOR folds' `(raw, outcome)` pairs and injects it for the current test fold, so
        the test-fold probability is calibrated with no peeking. Coordination note for
        Codex left in `codex-notes-for-claude.md`.
      - **Metadata persisted with each estimate**: added `Decision.model_meta`
        (JSON-primitive dict) and `record_signal` now folds it into the persisted signal
        `context` blob. Every `settlement_prob` decision carries `model`,
        `raw_probability`, `calibrated_probability`, `calibrator_version`, `reference_avg`,
        `drift_so_far`, `seconds_remaining`, `realized_vol_per_sec`.
      - `StrategyContext.brti_readings` added (default empty) as the strategy's input.

- [x] 4.3 Compare calibrated fair probability with side-specific executable prices and
      full expected friction before emitting a trade candidate.

      **Done** in the same module. `SettlementProbStrategy.evaluate`:
      1. builds `SettlementWindowFeatures` (§4.1) from `context.brti_readings`; HOLDs on
         `no_brti_readings`, `outside_time_window` (config'd min/max seconds remaining),
         or `baseline_probability_unavailable`;
      2. runs the baseline `settlement_probability` and passes it through the calibrator;
      3. computes the **side-specific** executable price — YES at `yes_ask`, NO at
         `100 - yes_bid` — and the post-friction EV per contract for each side:
         `p*(1-c) - (1-p)*c - entry_fee_rate(c) - exit_fee_rate(c)`, both fees at the
         versioned `FeeConfig` taker coefficient (FULL friction: entry fee **and** a
         modelled exit-leg fee, since a real stop/target exit pays a second taker fee);
      4. emits BUY_YES / BUY_NO for whichever side's edge clears `min_edge`, with a
         side-consistent `fair_probability`, an entry band (`±entry_band_cents`) so the
         engine rejects a materially worse fill, and the model metadata; otherwise
         `edge_below_threshold` HOLD.
      No sizing here — the strategy only emits probability + direction + band, exactly as
      design.md's "Separate prediction from execution and sizing" requires.

      25 unit tests across `test_settlement_window.py` (13, §4.1) and
      `test_settlement_prob.py` (12): calibrator monotonicity, the overconfident-model
      correction, out-of-range clamping, insufficient-data fallback; and the strategy's
      HOLD reasons, YES/NO entry on drift with a cheap price, injected-calibrator flow-
      through, and `min_edge` gating. Full suite 413 passed, ruff + pyright clean, no new
      dependencies.
- [ ] 4.4 Reimplement trend and pullback features on short-horizon BRTI/perpetual data, and report their incremental out-of-sample value against the settlement-aware baseline.
- [ ] 4.5 Add separately labeled experiments for microprice, public-trade imbalance, and quarter-hour opening effects; defer each when the required data coverage is insufficient.
- [ ] 4.6 Run reproducible KXBTC15M-only validation and document whether any candidate satisfies the promotion gate.

## 5. Perpetual Isolation and Execution Safety

- [ ] 5.1 Split perp strategy ledger, metrics, and promotion configuration from binary-event strategy reporting.
- [ ] 5.2 Disable market-neutral funding-carry classification unless a compatible linear hedge, rebalance cadence, complete fees, funding, and residual risk are modeled.
- [ ] 5.3 Implement idempotent order tracking, restart reconciliation, partial-fill handling, and stale-order cancellation for paper/perp execution.
- [ ] 5.4 Use anchored reduce-only exit triggers where supported and verify emergency-close fills before declaring a position closed.
- [ ] 5.5 Add failure-mode tests for restart with open orders, partial fills, unconfirmed emergency exits, and an unsupported binary hedge.

## 6. Operator Surface and Verification

- [ ] 6.1 Update the dashboard and run artifacts to show instrument scope, data freshness/provenance, model/calibration version, promotion status, and unresolved execution state.
- [ ] 6.2 Update strategy research and operator documentation to distinguish validated evidence, experiments, deferred data-dependent work, and disabled perp carry.
- [ ] 6.3 Run unit, integration, causal-regression, and walk-forward reproducibility tests; record the exact data/configuration versions used.
- [ ] 6.4 Validate paper-mode restart, reconciliation, anchored exits, stale-order handling, and kill-close confirmation before enabling any paper strategy.
