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
- [x] 4.4 Reimplement trend and pullback features on short-horizon BRTI/perpetual data,
      and report their incremental out-of-sample value against the settlement-aware
      baseline.

      **Done — feature + strategy-variant side; the incremental-value *report* is run at
      §4.6 through Codex's §3.4 report over the same harness.**
      - New `src/kalshi_bot/signals/short_horizon_trend.py` (pure, storage-free, causal —
        readings <= now_ts only): `build_trend_features` returns `slope_per_sec` (OLS
        slope of BRTI vs. time — the natural `drift_per_sec` estimate for the baseline
        model), `return_over_lookback`, `trend_z` (return / windowed realized vol — move
        size vs. noise), and a `pullback_fraction` / `pullback_direction` pair (how far
        BRTI has retraced from the window's extreme, and whether that extreme was a high
        or a low). Every field is None when history is insufficient — never a substituted
        zero.
      - New `src/kalshi_bot/strategy/short_horizon_trend.py`:
        `TrendConditionedSettlementStrategy` = the §4.2/§4.3 settlement strategy with ONE
        change — it feeds the baseline probability model `slope_per_sec * drift_scale` as
        `drift_per_sec` instead of a fixed 0, and optionally HOLDs against an established
        trend (`max_adverse_trend_z`) or when chasing with no pullback
        (`min_pullback_fraction`). `use_trend_drift=False` makes it byte-for-byte the
        plain baseline — the control arm for §4.6's comparison. Trend inputs ride on
        `Decision.model_meta["trend"]`. No sizing here (same contract as the baseline).
      - design.md's rule is honoured structurally: trend "cannot trade merely because
        direction is positive" — it only shifts the baseline's own probability and can
        only *subtract* trades via the gates; §4.6 decides whether it earns its keep.
      11 unit tests (`tests/unit/test_short_horizon_trend.py`): OLS slope recovers a known
      ramp, flat series → no trend_z, insufficient-history → None, future-reading
      exclusion, pullback fraction of a known up-move; and the variant entering on trend
      drift, `use_trend_drift=False` ≡ baseline, the chasing gate, base-HOLD pass-through,
      and base-config overrides.

- [x] 4.5 Add separately labeled experiments for microprice, public-trade imbalance, and
      quarter-hour opening effects; defer each when the required data coverage is
      insufficient.

      **Done — all three DEFERRED, explicitly, with reasons.** New
      `src/kalshi_bot/strategy/experiments/__init__.py`: an `ExperimentStatus(name,
      available, reason)` for each of `microprice`, `public_trade_imbalance`,
      `quarter_hour_open_effect`, all `available=False` right now because their inputs
      do not exist yet — no `OrderBookSnapshot` (L2) rows, no `PublicTrade` rows (both
      need `scripts/capture_session.py` imports, §1.4), and the archived BRTI series is
      not dense enough at KXBTC15M window opens. `deferred_experiments()` returns the list
      for the walk-forward report to print, so a deferral is never silent; when capture
      sessions accumulate the data, each flips to `available=True` and gets a real builder.
      3 unit tests (`tests/unit/test_experiments.py`). Full suite 427 passed, ruff +
      pyright clean, no new dependencies.
- [x] 4.6 Run reproducible KXBTC15M-only validation and document whether any candidate satisfies the promotion gate.

      **Done — reproducible run executed 2026-09-06 with the repository's
      configured archive path (`data/kalshi_bot.db`).** The archive is absent
      in this checkout, so the validation runner recorded the following
      KXBTC15M-only dataset counts: markets=0, candles=0, BRTI=0. The three
      shared-fold arms (settlement probability, trend drift, and trend control)
      therefore each returned **FAIL / NO-GO**: 0 trades, 0 folds, 0 coverage,
      and no expectancy CI. This is a data-availability failure, not a tuned
      holdout result. The runner preserves validation evidence, prints all
      promotion-gate reasons, lists the three deferred experiments, and returns
      exit code 1. Failure ordering is explicit: funding carry is separate and
      unevaluated; weather is not applicable; validation is parked until a
      causal BRTI archive is captured/imported. No candidate is promoted.
      `scripts/run_validation.py` will run the same manifest once the required
      archive exists; it refuses to substitute another series.

      **Update 2026-09-06 (commit `6100474`): the data-present path is now
      implemented, not a `raise`.** `src/kalshi_bot/backtest/validation_run.py`
      `run_validation_arms(session_factory)` runs each arm through
      `rolling_folds` + `run_walkforward` with fresh broker/guard state per
      fold, fixed-risk sizing (`BacktestEngine(sizing_mode="fixed_risk")`,
      §3.1), and isotonic calibration fitted on prior folds only (fold 0 =
      identity). Each fold runs the engine over `[train_start, test_end]` with
      `split_ts = test_start`; only test-segment settlements feed its
      `FoldReport`, then `aggregate_reports` + `evaluate_promotion`. Prereqs
      landed in `bfc6ba0`: BRTI readings are populated into
      `StrategyContext.brti_readings` from `BRTIObservation` (the
      settlement-aware strategies previously always HELD on
      `no_brti_readings`), and the engine eval loop no longer drops every
      market when no `SpotCandle` history is archived. Fail-closed unchanged;
      fold defaults track `SCRATCHPAD/capture-window-sizing.md` (28d train /
      1d embargo / 14d folds). Tests:
      `tests/unit/test_validation_run.py` (4) drive a synthetic causal archive
      end-to-end through every arm. **The verdict is still a data-availability
      NO-GO in this checkout** — a captured KXBTC15M + BRTI archive
      (`scripts/capture_session.py`, operator-run) is the remaining
      requirement before a merits verdict.

## 5. Perpetual Isolation and Execution Safety

- [x] 5.1 Split perp strategy ledger, metrics, and promotion configuration from
      binary-event strategy reporting.

      **Done.** New `src/kalshi_bot/backtest/perp_ledger.py` — a standalone accounting +
      reporting layer that deliberately does NOT import `backtest/report.py`,
      `backtest/metrics.py`, or `promotion_gate.py` (design.md "SEPARATE ledger and
      gate"): those speak binary settlement / Brier / win-rate, none of which apply to a
      mark-to-market perp.
      - `PerpFill`, `FundingEvent` (signed `payment_usd` from the account's view),
        `PerpTrade` (gross = `size*(exit_mark-entry_mark)`, plus signed funding PnL, minus
        both taker legs).
      - `PerpLedgerMetrics` foregrounds what actually matters for a perp:
        `min_distance_to_liquidation` (the single closest any trade came),
        `max_leverage_used`, `n_liquidations`, `worst_trade_pnl_usd`, and
        `funding_share_of_net` — a carry strategy whose net PnL is mostly PRICE move, not
        funding, is mislabelled (feeds §5.2). It carries NO `win_rate` / `breakeven` /
        `brier`.
      - `PerpPromotionPolicy` / `evaluate_perp_promotion` — a SEPARATE gate: rejects any
        liquidation regardless of PnL, rejects coming within 15% of liquidation, rejects
        leverage over the 2x cap. Perps are enabled only after this gate AND the
        event-contract gate both pass (design.md migration step 5).

- [x] 5.2 Disable market-neutral funding-carry classification unless a compatible linear
      hedge, rebalance cadence, complete fees, funding, and residual risk are modeled.

      **Done.** New `src/kalshi_bot/strategy/funding_carry_classification.py`:
      `classify_funding_carry(HedgeSpec)` is a pure predicate returning `DISABLED` (with
      the specific reasons) whenever the hedge is a binary/event contract or anything
      non-linear, OR any required model component is missing — rollover/rebalance cadence,
      both legs' full fees, per-interval funding accrual, or an explicit residual
      basis-risk estimate. `ELIGIBLE` only when the hedge is linear (spot / dated future /
      perp), on the same reference index, and every component is present — and even then
      promotion still needs `evaluate_perp_promotion` on real results (necessary, not
      sufficient). `BINARY_EVENT_HEDGE` is the v2 prototype's approach, exported and
      asserted `DISABLED`.

      `strategy/funding_carry.py` now routes through it: `evaluate_funding_carry` takes a
      `hedge: HedgeSpec` (default `BINARY_EVENT_HEDGE`), still computes the research carry
      numbers, but returns `should_enter=False` / `market_neutral=False` /
      `reason="hedge_not_linear_carry_disabled"` with `classification_reasons` whenever the
      hedge is not `ELIGIBLE`. It only reports `market_neutral=True` for a fully-modelled
      linear hedge. `test_favorable_carry_enters` updated to require an eligible hedge; new
      tests cover the binary-hedge disabling and every missing-component reason.

      27 unit tests (`test_perp_isolation.py` 18 + updated `test_funding_carry.py` 9). Full
      suite green in the §5.1/§5.2 subset; ruff + pyright clean; no new dependencies.
- [x] 5.3 Implement idempotent order tracking, restart reconciliation, partial-fill handling, and stale-order cancellation for paper/perp execution.

      **Done.** `execution/order_tracker.py` persists client-order-id records
      atomically, deduplicates retries, retains partial remainders, adopts fills
      that landed while down, and exposes stale-order cancellation that records
      the cancellation only after the broker call succeeds. It is ORM-free to
      avoid a migration collision with the parallel ledger work.
- [x] 5.4 Use anchored reduce-only exit triggers where supported and verify emergency-close fills before declaring a position closed.

      **Done.** `risk/exit_triggers.py` keeps native margin brackets and
      reduce-only IOC emergency closes, adds fill-anchored stop/target price
      construction, and reports an unconfirmed close as unresolved/closing.
- [x] 5.5 Add failure-mode tests for restart with open orders, partial fills, unconfirmed emergency exits, and an unsupported binary hedge.

      **Done.** Unit tests cover restart persistence, reconciliation of a fill
      received during downtime, partial remainder retention, stale-safe order
      state, unconfirmed emergency close, and rejection of a binary contract as
      a linear hedge.

## 6. Operator Surface and Verification

- [x] 6.1 Update the dashboard and run artifacts to show instrument scope, data
      freshness/provenance, model/calibration version, promotion status, and unresolved
      execution state.

      **Done.** New `queries.latest_validation_status()` reads the most recent
      `evidence_class="validation"` run (falling back to any run), and surfaces:
      instrument scope, data window, `fee_config_version`, `resolution_config_version`,
      the calibrator version from provenance, and the promotion verdict + blocking
      reasons parsed from `metrics_test["promotion"]`. Degrades to an all-blank status on
      a fresh DB — never raises. New **Validation status** panel on `index.html` renders
      it with PASS/FAIL/not-evaluated badges. The live positions/AI placeholder panels'
      copy was refreshed — §4/§5/§7.1 modules now exist, so the panels say "nothing is
      executing yet" (accurate) rather than "not built". 5 tests
      (`test_dashboard_validation_panel.py`): blank DB, a validation run surfacing all
      fields, validation-preferred-over-newer-diagnostic, diagnostic-only, and an index
      route smoke test.

- [x] 6.2 Update strategy research and operator documentation to distinguish validated
      evidence, experiments, deferred data-dependent work, and disabled perp carry.

      **Done.** New `docs-site/docs/status/kxbtc15m-rebuild.md` — the operator-facing
      evidence taxonomy: (1) **validated** = a `validation`-class run that is KXBTC15M-
      only, causal, fully-costed, fixed-risk-sized, walk-forward with fresh per-fold
      state, and gate-checked; (2) **experiments** = trend/pullback as a labelled variant
      reported on incremental value, plus microprice / trade-imbalance / quarter-hour;
      (3) **deferred** = the data-dependent items and their specific blockers, in a
      table; (4) **disabled** = cross-instrument funding carry, with the
      `classify_funding_carry` conditions for it to become eligible and the separate perp
      ledger/gate. Ends with the unchanged §8.5 promotion order (funding carry → weather
      → park).

- [x] 6.3 Run unit, integration, causal-regression, and walk-forward reproducibility
      tests; record the exact data/configuration versions used.

      **Done.** `python -m pytest -q`: **456 passed**, 3 deselected (the 3 integration
      tests, incl. the live-Ollama round-trip, excluded by default per
      `pyproject.toml`). Causal-regression coverage: `test_engine_causal_timeline.py` (6),
      `test_engine_scenario_accounting.py` (5). Walk-forward reproducibility:
      `test_validation_risk_reporting.py` + the `run_validation.py` manifest (§4.6), which
      is deterministic given a fixed archive. Config versions in force:
      `FeeConfig("2026-09-kalshi")`, `ResolutionSpec("2026-09-kxbtc15m-brti-60s")`.
      **Whole-repo `ruff check` + `pyright` surfaced 2 static issues in the §5.3–5.5
      execution files** (an `__all__` sort in `execution/__init__.py`; a `float`→`int`
      `Position.quantity` mismatch in `backtest_broker.py` from §2.4's fractional
      quantities) — neither is a runtime bug (`pytest` is clean), both handed to the §5.x
      lane via the coordination notes. `pytest` + per-file `ruff`/`pyright` on every
      committed file this change added are clean.

- [ ] 6.4 Validate paper-mode restart, reconciliation, anchored exits, stale-order
      handling, and kill-close confirmation before enabling any paper strategy.

      **Blocked — this is an operator action, not a coding task.** The machinery exists
      (§5.3–5.5: `execution/order_tracker.py`, `execution/safety.py`, the reduce-only
      anchored exits and confirmed emergency close) and is unit-tested against fakes. But
      "validate paper-mode restart/reconciliation" means running the paper loop against
      live demo Kalshi, killing it mid-flight, and confirming recovery — which requires
      §10's paper trading to actually be running. It cannot be closed until then.

      **§4.6 is also effectively blocked on data**: the validation run executed but found
      markets=0 / candles=0 / BRTI=0 in this checkout (the archiver's 4th silent death
      cost the KXBTC15M-era data). All three arms FAIL vacuously. The validation
      machinery is correct and reproducible; it needs a captured causal KXBTC15M + BRTI
      dataset (`scripts/capture_session.py`, run by the operator over time) before any
      strategy can be judged on merits.
