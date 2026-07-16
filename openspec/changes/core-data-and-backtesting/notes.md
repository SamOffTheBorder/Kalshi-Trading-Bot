# Implementation notes: core-data-and-backtesting

## Task 2.2 spike findings (2026-07-15, live public API)

**Series confirmed** (all exist, unauthenticated access works):

| Series | Title | Frequency |
|---|---|---|
| KXBTC | Bitcoin range | hourly |
| KXBTCD | Bitcoin price Above/below | hourly |
| KXETH | Ethereum range | hourly |
| KXETHD | Ethereum price Above/below | hourly |

**Critical finding — shallow retention**: settled markets are only queryable back to
**~2026-06-01** (probes at 2026-01-15/02-01/03-01/04-01/05-01 all returned zero; 2026-06-01
returned markets). The public API is a ~6-week rolling window for these series, **not a deep
archive**. Consequences:

1. `scripts/fetch_historical.py` must run regularly (cron/scheduled) so our own DB becomes the
   deep archive — every week we wait, a week of history ages out upstream.
2. The initial backtest window is ~6 weeks of hourly markets (~1,000 markets/page, tens of
   thousands of settled markets available in-window — plenty of trade samples, but a short
   calendar window). Out-of-sample split remains viable (e.g., first 4 weeks train / last 2
   test) but seasonal/regime robustness claims are limited until our archive grows.
3. Third-party archives (kalshibacktest.com free tier, lycheedata.com bulk) are the fallback
   if deeper history is needed before our archive matures — per design, only if genuinely needed.

**Payload format** (differs from v1-era integer-cents assumptions):

- Candlesticks: `end_period_ts` (epoch s), `price` / `yes_bid` / `yes_ask` are dicts of
  decimal-dollar strings — `open_dollars`, `high_dollars`, `low_dollars`, `close_dollars`
  (+ `mean_dollars` on `price`); `"0.0100"` = 1 cent. `volume_fp` / `open_interest_fp` are
  decimal strings ("1.00"). `price` dict is empty `{}` for periods with no trades.
- 1-min candles are sparse (only periods with activity); 60-min candles reliably present.
- Markets: `strike_type` ("greater"/…), `floor_strike`, `cap_strike`, `result` ("yes"/"no"),
  ISO `open_time`/`close_time`.
- Unauthenticated requests get 429s well below the documented Basic-tier 20/s — client default
  lowered to a conservative rate; backoff handles the rest.

## Engine smoke-run discoveries (2026-07-15)

1. **Hourly markets need 1-minute candles.** An hourly market gets exactly one 60-minute
   candle, timestamped at the market's close — too late to trade. The engine defaults to
   1-minute granularity with a 300s evaluation stride (matching a realistic live polling
   cadence); the archiver now runs `--period 1`.
2. **Zero-volume strikes skipped at fetch time.** ~183 strike-markets per hourly period,
   most far-OTM with zero lifetime volume. Fetching their candles is one request each and
   simulating fills in never-traded markets is fantasy anyway. `--include-zero-volume`
   exists for completeness runs. Market metadata rows are still archived for every strike.
3. Spot klines must be fetched before any backtest (`--series --spot` for spot-only).

## §8.1 First real backtest (2026-07-15, run #3) — GATE NOT CLEARED

Window: 2026-07-03 .. 2026-07-15 (~12 days archived), split 2026-07-12, $130, quarter-Kelly,
5% cap, pessimistic fills. 87,363 evaluations → 37 entries (gates are highly selective).

```
[train] trades=37 win_rate=59.5% vs breakeven=66.0% (margin -6.5%)
        net_pnl=+$68.95 (fees $16.47) sharpe=0.48 max_dd=25.8%
[test]  no trades
```

**Honest reading — the metrics design did its job:**

1. **Win-rate margin is NEGATIVE (-6.5%).** 59.5% wins sounds good and PnL is +$68.95,
   but the fee-adjusted breakeven at the average entry price (~63¢) is 66%. The profit
   came from favorable dollar-weighting of a 37-trade sample, not a validated
   count-weighted edge. This is exactly the v1 failure signature the side-by-side
   breakeven display exists to catch — v1 would have called this a win.
2. **25.8% max drawdown tripped the PAUSE guard mid-run**, and the guard stayed paused
   into the test window → **zero out-of-sample trades → the gate cannot be evaluated,
   therefore it is not cleared.** A strategy that hits its own pause threshold in-sample
   fails the "drawdown within guard tolerance" criterion regardless of PnL.
3. 37 trades is far too small a sample to calibrate go/no-go thresholds (§8.2's ask).

**Follow-ups before re-running the gate:**
- Grow the archive (rolling window: earliest ~2026-06-01 upstream; archiver must run daily)
- Investigate entry concentration: which series/hours produced the 37 entries and the
  drawdown cluster (signals table has full audit trail, run_id=3)
- Methodological decision to record in the next run: whether the test segment should
  start with a fresh guard/bankroll (independent evaluation) or inherit train state
  (operationally realistic). Current engine inherits; keep, but report guard state at
  split so a starved test segment is visible rather than silent.
- Consider whether `min_edge=0.05` + probability bounds need recalibration once the
  signals audit trail shows the hold-reason distribution across all 87k evaluations.

## §8.2 Second backtest, wider window (2026-07-16, run #4) — GATE STILL NOT CLEARED, worse result

Window: 2026-05-10 .. 2026-07-16 (67 days, KXBTC+KXBTCD only — KXETH/KXETHD had zero archived
candles at run time), split 2026-06-29, $130, quarter-Kelly, 5% cap, pessimistic fills.
991,543 evaluations → 23 entries.

```
[train] trades=23 win_rate=52.2% vs breakeven=67.9% (margin -15.8%)
        net_pnl=-$35.63 (fees $2.37) sharpe=-0.78 max_dd=27.4%
[test]  no trades
```

**This is a materially worse and more informative result than run #3:**

1. **Win-rate margin widened from -6.5% to -15.8%.** Run #3's near-breakeven-looking PnL was
   noise from a 37-trade sample; with ~6x more calendar time the same strategy loses money
   outright (net PnL now negative, Sharpe negative). This is the expected behavior of a larger,
   more representative sample revealing a real (lack of) edge rather than sampling luck.
2. **Same failure mode as run #3**: drawdown (27.4%) tripped PAUSE and the test segment again
   got zero trades — two consecutive runs where the strategy exhausts its own risk budget
   before ever reaching out-of-sample evaluation. This is now a pattern, not a fluke.
3. **Entry count dropped from 37 to 23 despite ~6x more data** — the gates (min_edge, BS/MC
   divergence, probability bounds) are filtering harder over the longer window, and what gets
   through is losing. Fewer, worse trades on more data is the opposite of what a real edge
   should look like.

**Conclusion**: `crypto_mispricing` as currently configured does not have a validated edge on
KXBTC/KXBTCD 1-min data. Per the plan's explicit phase-gate rule, this strategy does NOT
proceed to paper trading. Before any further gate attempt:

- Pull the run_id=4 signals audit trail and characterize the 23 trades: which hour-of-day/
  strike-distance/vol-regime they cluster in, and whether the divergence guard or probability
  bounds are systematically letting through a biased subset.
- Re-examine `min_edge` (currently 0.05) and `max_model_divergence` (0.06) — both were picked
  as reasonable defaults, not calibrated against data. This run is exactly the calibration
  data that was missing before.
- Once KXETH/KXETHD have real coverage, re-run including them — a strategy failing on BTC
  alone doesn't rule out ETH behaving differently, though the prior is now for consistent
  underperformance given the shared strategy logic and pricing model.
- Consider whether the fill model's pessimism (worst-of-bar price) is appropately calibrated
  vs. what live execution would actually achieve — but do NOT loosen this to manufacture a
  pass; the whole point of pessimistic-by-default is that a strategy needs to survive it.

## §8.2 audit trail finding — root cause identified (2026-07-16)

Pulled all 23 run_id=4 trades (market_ticker, side, entry price, timing, outcome). **The
"23 trades over 67 days" framing is misleading — all 23 fired within a single ~15-hour window
on 2026-05-16, all on KXBTC (none KXBTCD), 21/23 on the NO side, nearly all at closely-spaced
`B78xxx` strikes** (a tight band around $78,000). This is not a diversified sample of the
strategy's behavior across two months — it's one clustered episode.

**Reading**: BTC was evidently trending toward/through the $78k level that day. The strategy
kept independently re-evaluating adjacent hourly range markets straddling that level, and its
pricing model kept computing a NO edge that the market disagreed with — and the market was
right more often than not (12 losses vs. 11 wins by count, but losses skew larger: -$68.14
total losses vs. +$32.51 total wins). This looks like a trending/directional regime the
digital-option model (which assumes the current spot + static vol, not directional drift) is
structurally not equipped to price well — repeatedly fading a move instead of recognizing one.

**This reframes the whole result**: the gate isn't failing because of scattered bad luck across
two months: it's failing because on the *one* day with enough volatility to trip the strategy's
edge threshold at all, it walked into a single adverse trending episode and keeps re-entering
into it. Implications:
- The archive's 67-day window has real trading activity on essentially one day — coverage is
  wide in calendar time but narrow in "days the strategy actually found an edge." More archived
  history won't fix this; it'll just add more mostly-idle days unless another volatile episode
  is captured.
- A same-day, same-strike-band, same-side entry cluster is exactly what a **per-day or
  per-directional-move position cap** would limit — the strategy currently has no such guard;
  only the portfolio-level position/Kelly caps apply per-trade, not per-episode.
- Before touching `min_edge`/divergence thresholds, the higher-priority question is whether the
  model needs a drift/momentum-awareness component (or a trend-filter HOLD) — an edge that only
  shows up during trends and then loses to the trend is a specification gap, not a threshold
  miscalibration.

**Revised next steps** (supersedes the prior "recalibrate thresholds" framing):
1. Add a same-day/same-underlying entry cap to `crypto_mispricing` or `risk/` (e.g., max N
   entries per series per rolling window) so one clustered episode can't dominate a backtest
   or, later, a live run.
2. Investigate whether a simple trend filter (e.g., recent realized drift vs. the model's
   zero-drift assumption) should gate entries or adjust the probability estimate.
3. Once KXETH/KXETHD have coverage, check whether they show the same single-day-clustering
   pattern — if so, this is a structural strategy gap, not a BTC-specific fluke.
4. Re-run the backtest only after (1) is in place, so the next result reflects diversified
   entries rather than one episode's outcome.

## §8.2 Run #5 with EntryThrottle (2026-07-16) — cluster cap works; guard defect exposed

Implemented `risk/entry_throttle.py` (max 3 filled entries per series per rolling 24h,
`max_entries_per_series_window` / `entry_throttle_window_hours`) and re-ran the same window
(2026-05-10 .. 2026-07-16, split 2026-06-29, $130, pessimistic fills). 991,311 evaluations →
48 entries.

```
[train] trades=48 win_rate=52.1% vs breakeven=53.2% (margin -1.1%)
        net_pnl=+$98.24 (fees $23.53) sharpe=0.32 max_dd=26.8%
[test]  no trades   ← third consecutive starved test segment
```

**The throttle did what it was built to do**: entries now spread across 16 distinct days
(2026-05-16 .. 05-31, max 3/day) instead of 23 in one 15-hour episode. Win-rate margin
improved -15.8% → -1.1%, net PnL flipped positive, and average entry cost dropped 63¢ → 51¢
(breakeven 67.9% → 53.2%). One clustered episode no longer dominates the sample.

**But the test segment starved again, and this time the root cause is nailed down** (audit
of the equity curve + signals table, run_id=5):

- Equity peaked at $311.73 (~05-29/30 intraday), then the 05-30/31 losses took it to $228.24
  — a 26.8% drawdown that tripped PAUSE.
- **All-time-peak PAUSE is permanently sticky in a settle-to-flat book, by construction**:
  paused ⇒ no entries ⇒ book settles flat ⇒ equity constant ⇒ drawdown-from-all-time-peak
  can never shrink ⇒ paused forever. There is no code path back to NORMAL.
- The cost was measurable: the signals table shows **~1,000 BUY candidates/day from 06-24
  onward — including the entire test window — every one blocked by the stuck guard.**
  (22,929 BUY signals total out of 991,311 evaluations, 2.3% — the strategy gates are
  selective; `insufficient_edge` accounts for 76% of holds.)
- This same mechanism, not strategy behavior, is why runs #3 and #4 also had zero
  out-of-sample trades.

**Fix (same date): trailing-window peak.** `DrawdownGuard` now measures drawdown against
the max equity in a trailing window (`drawdown_peak_window_days`, default 7; monotonic-deque
sliding max). An old peak ages out, so PAUSE re-arms after at most one window of flat equity.
HALT remains all-time-sticky pending explicit human reset. `peak_window_s=None` preserves
the old semantics for callers without timestamps. **This is a risk-semantics change worth
explicit review before Phase 2** — recorded here per the plan's "recalibrate the guard
against backtest output" clause.

## §8.2 Run #6 with trailing-peak guard (2026-07-16) — first real OOS segment: GATE FAILED DECISIVELY

Same window/params as run #5, guard now re-arms (7-day trailing peak). 988,529 evaluations →
128 entries; the guard paused and recovered repeatedly instead of dying on 05-31.

```
[train] trades=100 win_rate=53.0% vs breakeven=53.3% (margin -0.3%)
        net_pnl=+$657.69 (fees $160.97) sharpe=0.62 max_dd=42.5%
[test]  trades=28  win_rate=32.1% vs breakeven=46.2% (margin -14.0%)
        net_pnl=-$238.88 (fees $43.33)  sharpe=-0.27 max_dd=42.9%
```

**This is the run the whole apparatus was built for — the first out-of-sample segment with
trades, and it fails everything:**

1. **OOS win rate 32.1% vs 46.2% breakeven (margin -14.0%), net -$238.88.** The test trades
   are exactly what we wanted structurally — spread over 7 days, both series, both sides,
   throttle-capped — a genuinely diversified sample, and it still loses. Worse: a single
   +$384.16 win (2026-07-09) masks the rest; the other 27 test trades lost -$623 combined.
2. **Train +$657.69 is Kelly-compounded dollar-weighting, not edge**: count-weighted margin
   is -0.3%, and the weekly PnL is two hot weeks (+$948 in weeks 22-23) surrounded by
   givebacks (-$389 in weeks 24-25). v1 would have shipped this. The gate says no.
3. **Trade count rose 48 → 128 with the guard fixed** — runs #3-#5's "selective" entry counts
   were partly an artifact of the stuck guard, not just strategy selectivity.
4. **Trailing-peak side effect flagged**: segment max_dd hit 42.5%/42.9% — beyond the 40%
   HALT line — but HALT never fired, because drawdown-from-*trailing*-peak stayed below it
   during slow bleeds. The trailing window fixes PAUSE re-arm but also softens HALT.
   Design question for review: HALT should probably be measured against a longer/absolute
   reference (e.g., initial bankroll or all-time peak) rather than the same 7-day window.

**Conclusion: `crypto_mispricing` (zero-drift BS/MC, current gates) has NO out-of-sample
edge. Per the plan's phase-gate rule it does not proceed to paper trading in this form.**
The remaining untested structural hypothesis is trend/drift-awareness (the model fades
directional moves it cannot see). Options from here, in recommended order:
1. Add a realized-drift/trend filter (HOLD when recent drift contradicts the zero-drift
   assumption), re-run — the last cheap, falsifiable iteration on this strategy.
2. If OOS margin is still negative with the filter: park crypto mispricing and take the
   framework (which now demonstrably works end-to-end: archive → backtest → honest OOS
   verdict) to the plan's other strategy families (weather/econ), where pricing may be
   less efficient than crypto.

## Design open-question resolutions

- "Which crypto series have deep-enough candlestick history?" → All four target series have
  identical ~6-week retention. Split: time-based within the available window, plus continuous
  archiving to extend it. Recorded above.
