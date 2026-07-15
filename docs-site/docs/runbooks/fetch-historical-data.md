# Fetch historical data

The Kalshi public API is a **~6-week rolling window** — settled markets older than that
disappear upstream. Our local database *is* the deep archive, so this needs to run
regularly. Every week you don't run it, a week of history is gone for good.

## Commands

```bash
# Archive all four crypto series at 1-minute granularity (the default that matters —
# hourly markets are only backtestable at 1-min bars):
uv run python scripts/fetch_historical.py --period 1

# Also refresh spot klines (needed by every backtest; ~10 requests, fast):
uv run python scripts/fetch_historical.py --series --spot

# Coverage report only (no fetching):
uv run python scripts/fetch_historical.py --report --period 1
```

## Behavior notes

- **Resumable**: markets whose candles are already stored are skipped; re-runs are cheap
  and idempotent (DB unique constraints dedup at the schema level too).
- **Zero-volume skip**: only ~18% of strike-markets ever trade. Candles are fetched only
  for markets with nonzero lifetime volume (`volume_fp` in the API payload); metadata rows
  are stored for every strike regardless. `--include-zero-volume` overrides.
- **Rate limits**: the client self-throttles to 8 req/s (unauthenticated access throttles
  well below the documented Basic-tier 20/s) with exponential backoff on 429/5xx.
- No credentials are needed for any of this.

## Recommended schedule

Windows Task Scheduler (or cron on the future home server), daily:

```
uv run python scripts/fetch_historical.py --period 1
uv run python scripts/fetch_historical.py --series --spot
```
