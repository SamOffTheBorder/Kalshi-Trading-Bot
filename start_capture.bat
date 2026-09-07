@echo off
REM ===========================================================================
REM  KXBTC15M validation data capture  (kxbtc15m-validation-rebuild)
REM ===========================================================================
REM  Double-click to open a visible capture window. Close it anytime to stop --
REM  every phase is resumable and nothing is lost.
REM
REM  Each cycle:
REM    1. refresh the last ~3 days of KXBTC15M markets + 1-min contract candles
REM       (Kalshi public API, unauthenticated)
REM    2. backfill Kalshi crypto-perp funding history for the nine registry
REM       assets (KXBTCPERP/KXETHPERP/... -- /margin/funding_rates/historical,
REM       read-only authenticated). Funding IS backfillable, so this is a cheap
REM       one-shot pull each cycle, idempotent -- it only writes new 8-hourly
REM       settlements.
REM    3. poll all nine CF Benchmarks crypto indices (BTC/ETH/SOL/XRP/DOGE/BNB/
REM       HYPE/NEAR/ZEC) for ~6 hours via Kalshi's authenticated passthrough
REM       (read-only market data; needs KALSHI_KEY_ID and
REM       secrets\kalshi_private_key.pem), recording observed_at / available_at
REM       honestly, per-index, and logging -- never filling -- gaps
REM    4. poll the nine crypto-perp settlement marks for ~6 hours
REM       (/margin/markets, read-only authenticated) with the same causal-
REM       timestamp and honest-gap discipline. Kalshi has no historical mark
REM       series, so a live poll is the only way to build one.
REM  then loops back to step 1.
REM
REM  Only BTC (BRTI) feeds the current KXBTC15M validation. The other indices
REM  and every perp series are captured now so ETH/SOL/... and perp validation
REM  later don't start from zero. To capture BTC only, change "--brti-index all"
REM  to "--brti-index BTC" and "--perp-asset all" to "--perp-asset BTC" below.
REM
REM  This never schedules itself and never runs unattended. It is a foreground
REM  window you start and stop by hand.
REM
REM  First run: let it complete one full BRTI poll cycle, then run
REM    uv run python scripts\run_validation.py --db data\kalshi_bot.db
REM  It will still be a NO-GO (not enough days yet) but it prints the real
REM  fill rate so the capture window can be re-planned. Target ~90 days.
REM ===========================================================================

cd /d "%~dp0"
title KXBTC15M Capture  (BRTI + contract candles)

REM 3-day lookback for the contract-candle refresh, in epoch seconds.
REM 259200 = 3 * 24 * 3600
for /f %%T in ('powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"') do set NOW=%%T
set /a START=%NOW% - 259200

:loop
echo.
echo === %DATE% %TIME%  refreshing KXBTC15M contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  backfilling crypto-perp funding history (idempotent) ===
uv run python scripts\capture_session.py --backfill-funding --perp-asset all

echo.
echo === %DATE% %TIME%  polling 9 CF Benchmarks crypto indices for ~6 hours (Ctrl+C to stop) ===
uv run python scripts\capture_session.py --poll-brti --brti-source kalshi --brti-index all --interval 60 --duration 21600

echo.
echo === %DATE% %TIME%  polling 9 crypto-perp settlement marks for ~3 hours (Ctrl+C to stop) ===
REM  Shorter than the BRTI poll: BRTI is the load-bearing feed for the current
REM  KXBTC15M validation, perp marks are ahead-of-need. Raise --duration here
REM  (up to match BRTI) once perp validation is the priority.
uv run python scripts\capture_session.py --poll-perp-marks --perp-asset all --interval 60 --duration 10800

echo.
echo === %DATE% %TIME%  cycle done -- gap report ===
uv run python scripts\capture_session.py --report

REM advance the lookback window for the next cycle
for /f %%T in ('powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"') do set NOW=%%T
set /a START=%NOW% - 259200
goto loop
