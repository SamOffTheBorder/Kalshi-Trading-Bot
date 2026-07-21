---
sidebar_position: 1
---

# Fetch historical data

The Kalshi public API is a **~6-week rolling window** — settled markets older than that
disappear upstream. Our local database *is* the deep archive, so this needs to run
regularly. Every day it doesn't run, that much history is gone for good.

In practice this is handled by the always-on archiver loop — see
[Archiver operations](./archiver-operations.md) — rather than run by hand. The commands
below are what that loop calls, useful for manual/one-off fetches or debugging.

## Commands

```bash
# Archive one or more series at 1-minute granularity (the default that matters —
# hourly/daily markets are only backtestable at 1-min bars):
uv run python scripts/fetch_historical.py --series KXBTC KXBTCD --period 1

# All default (crypto) series if --series is omitted:
uv run python scripts/fetch_historical.py --period 1

# Cap how long one series can occupy a single call before moving on (seconds; 0 = no
# limit). The archiver loop passes 180 per series so a brand-new series backfilling
# thousands of markets can't dominate a whole pass — it resumes automatically next call.
uv run python scripts/fetch_historical.py --series KXHIGHNY --period 1 --time-budget 180

# Also refresh spot klines (needed by every backtest; ~10 requests, fast):
uv run python scripts/fetch_historical.py --series --spot

# Coverage report only (no fetching):
uv run python scripts/fetch_historical.py --report --period 1
```

## Currently archived series

- **Crypto**: `KXBTC`, `KXBTCD`, `KXETH`, `KXETHD`
- **Weather**: `KXHIGHNY`, `KXHIGHLAX`, `KXHIGHMIA`, `KXHIGHCHI`, `KXHIGHAUS`,
  `KXHIGHDEN`, `KXHIGHPHIL`, `KXLOWTOKC`, `KXLOWTDC` — added 2026-07-16 as pivot
  insurance (see [Project scope](../project-scope.md#why-weather-joined-crypto-as-an-active-pipeline-target)),
  and prioritized *before* crypto in the archiver's rotation since they're far cheaper to
  fetch (~6 markets/day each vs. crypto's ~576).

## Behavior notes

- **Resumable**: markets whose candles are already stored are skipped; re-runs are cheap
  and idempotent (DB unique constraints dedup at the schema level too).
- **Zero-volume skip**: most strike-markets never trade (far more true for crypto hourlies
  than for weather — see the liquidity comparison in
  [Project scope](../project-scope.md)). Candles are fetched only for markets with
  nonzero lifetime volume (`volume_fp` in the API payload); metadata rows are stored for
  every strike regardless. `--include-zero-volume` overrides.
- **Rate limits**: the client self-throttles to 8 req/s (unauthenticated access throttles
  well below the documented Basic-tier 20/s) with exponential backoff on 429/5xx.
- No credentials are needed for any of this — it's all public market data.
