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

## Design open-question resolutions

- "Which crypto series have deep-enough candlestick history?" → All four target series have
  identical ~6-week retention. Split: time-based within the available window, plus continuous
  archiving to extend it. Recorded above.
