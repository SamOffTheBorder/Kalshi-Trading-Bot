@echo off
REM ===========================================================================
REM  KXBTC15M validation data capture  (kxbtc15m-validation-rebuild)
REM ===========================================================================
REM  Double-click to open a visible capture window. Close it anytime to stop --
REM  every phase is resumable and nothing is lost.
REM
REM  Each cycle:
REM    1. refresh the last ~3 days of markets + 1-min contract candles for
REM       BTC/ETH/SOL/XRP's 15-minute and hourly event series (Kalshi public
REM       API, unauthenticated). Kalshi runs TWO distinct hourly series per
REM       asset that both close on the hour: a THRESHOLD ladder (KX{A}D,
REM       "above $X") and a RANGE ladder (KX{A}, "between $X and $Y",
REM       strike_type=between) -- zero ticker overlap between them. Both are
REM       captured for BTC/ETH/XRP; SOL has no range series on the exchange
REM       (KXSOL/KXSOLRANGE return 0 markets) so it only has KXSOL15M+KXSOLD:
REM         KXBTC15M, KXBTC (range),  KXBTCD (threshold)
REM         KXETH15M, KXETH (range),  KXETHD (threshold)
REM         KXSOL15M,                 KXSOLD (threshold; no range exists)
REM         KXXRP15M, KXXRP (range),  KXXRPD (threshold)
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
REM    5. snapshot the current funding estimate for each crypto perp. Kalshi
REM       does not serve historical estimates, so this records only what is
REM       observable at the end of the manually run capture cycle.
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
uv run python scripts\capture_session.py --capture --series KXBTC15M --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXBTC hourly RANGE contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXBTC --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXBTCD hourly THRESHOLD contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXBTCD --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXETH15M contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXETH15M --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXETH hourly RANGE contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXETH --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXETHD hourly THRESHOLD contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXETHD --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXSOL15M contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXSOL15M --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXSOLD hourly THRESHOLD contract data (last 3 days; no range series exists for SOL) ===
uv run python scripts\capture_session.py --capture --series KXSOLD --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXXRP15M contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXXRP15M --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXXRP hourly RANGE contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXXRP --start-ts %START% --end-ts %NOW%

echo.
echo === %DATE% %TIME%  refreshing KXXRPD hourly THRESHOLD contract data (last 3 days) ===
uv run python scripts\capture_session.py --capture --series KXXRPD --start-ts %START% --end-ts %NOW%

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
echo === %DATE% %TIME%  capturing current crypto-perp funding estimates ===
uv run python scripts\capture_session.py --capture-funding-estimates --perp-asset all

echo.
echo === %DATE% %TIME%  cycle done -- gap report ===
uv run python scripts\capture_session.py --report

REM advance the lookback window for the next cycle
for /f %%T in ('powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"') do set NOW=%%T
set /a START=%NOW% - 259200
goto loop
