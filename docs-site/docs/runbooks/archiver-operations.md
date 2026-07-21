---
sidebar_position: 2
---

# Archiver operations

The archiver is `scripts/archiver_loop.py`, launched via `start_archiver.bat` as a
visible, titled console window ("Kalshi Archiver"). It repeatedly calls
`fetch_historical.py` across every archived series, then sleeps (default 30 minutes) and
repeats. It's the thing keeping [§8.4 validation](../roadmap.md#84-frozen-config-validation--the-current-blocker)
moving — every hour it's down is an hour of validation data that doesn't get collected.

## Starting it

Double-click `start_archiver.bat` in the repo root, or from PowerShell:

```powershell
Start-Process -FilePath "start_archiver.bat" -WorkingDirectory "<repo root>"
```

This opens a titled console window. **Closing that window stops archiving** — it's
designed to be visible and easy to stop on purpose, not hidden.

## Checking it's actually alive

The window being open isn't quite proof by itself — check the log is moving:

```bash
tail -5 logs/archiver_loop.log
```

If the timestamps are more than ~30–45 minutes old (one sleep cycle plus a pass), or the
last line is `Stopped.` with no restart since, it's down. A quick DB freshness check
confirms which series are stale:

```bash
uv run python -c "
import sqlite3
con = sqlite3.connect('data/kalshi_bot.db')
for r in con.execute('''SELECT m.series_ticker, datetime(max(c.end_period_ts),'unixepoch')
    FROM candles c JOIN kalshi_markets m ON c.market_ticker=m.ticker
    WHERE c.period_minutes=1 GROUP BY m.series_ticker'''):
    print(r)
"
```

## Restarting after it's stopped

Safe to just re-run `start_archiver.bat` — every fetch is resumable (see
[Fetch historical data](./fetch-historical-data.md#behavior-notes)), so a stopped-and-restarted
archiver never double-counts or corrupts anything, it just picks up wherever the DB says
it left off.

## Known reliability issue

The archiver has stopped unresponsively **multiple times** during Phase 1 (several
separate incidents between 2026-07-16 and 2026-07-21, gaps ranging from a few hours to
over two days). Each time, the log shows a clean `Stopped.` line — the signature of a
`KeyboardInterrupt`, not a crash — which points at something in the OS/session
environment (sleep, lock, session changes) interrupting the console window rather than a
bug in the loop itself. Two things have already been hardened in response:

- **Rotating file logging + per-pass crash recovery** — a genuine crash in one pass no
  longer takes down the whole loop, and there's now always a log to diagnose from
  (`logs/archiver_loop.log`).
- **`--time-budget`** on `fetch_historical.py` — a brand-new series backfilling
  thousands of markets used to look identical to a hang; now it's capped per series per
  pass and resumes automatically.

**What hasn't been changed, on purpose**: converting this to a Windows Scheduled Task
would fix the underlying reliability problem structurally (auto-restart, survives
logoff/lock, no window to accidentally close) — this was proposed and explicitly
declined in favor of keeping the visible console window. The accepted tradeoff is manual
vigilance: check the log/DB freshness periodically and restart when needed, per this
page. If gaps keep costing meaningful validation time, revisit that decision.
