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

## Design open-question resolutions

- "Which crypto series have deep-enough candlestick history?" → All four target series have
  identical ~6-week retention. Split: time-based within the available window, plus continuous
  archiving to extend it. Recorded above.
