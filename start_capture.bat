@echo off
setlocal enabledelayedexpansion
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
REM       Before each series is fetched, scripts\series_is_current.py checks
REM       whether that series' candles already reach this cycle's window end
REM       (within one candle period) and skips the fetch if so -- so a series
REM       that's already caught up doesn't cost an API pass every cycle.
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
REM    4. poll the nine crypto-perp settlement marks for ~3 hours
REM       (/margin/markets, read-only authenticated) with the same causal-
REM       timestamp and honest-gap discipline. Kalshi has no historical mark
REM       series, so a live poll is the only way to build one. NOTE: Kalshi's
REM       demo environment has renumbered these tickers before without notice
REM       (KXBTCPERP -> KXBTCPERP1, etc.) and dropped assets with no active
REM       demo contract -- capture_session.py fails loudly when that happens
REM       (NoCryptoPerpsMatchedError) rather than silently no-op'ing. Step 4
REM       failing does not stop steps 5-6 below; check the console output if
REM       perp marks stop advancing in capture_status.py.
REM    5. snapshot the current funding estimate for each crypto perp. Kalshi
REM       does not serve historical estimates, so this records only what is
REM       observable at the end of the manually run capture cycle.
REM  then loops back to step 1.
REM
REM  RESILIENCE: every step below is wrapped so a single step's failure
REM  (bad ticker, exchange renumbering, transient network error) prints and
REM  continues to the next step instead of killing the whole window. This is
REM  exactly what silently stopped perp-mark capture for ~6 days once already
REM  (2026-09-08 -> 2026-09-14, see NoCryptoPerpsMatchedError above) -- the
REM  .bat had no error handling, so one uncaught exception in step 4 took
REM  down steps 5-6 and the loop-back with it for every subsequent cycle.
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

call :capture_series KXBTC15M 15 "KXBTC15M contract data"
call :capture_series KXBTC 60 "KXBTC hourly RANGE contract data"
call :capture_series KXBTCD 60 "KXBTCD hourly THRESHOLD contract data"
call :capture_series KXETH15M 15 "KXETH15M contract data"
call :capture_series KXETH 60 "KXETH hourly RANGE contract data"
call :capture_series KXETHD 60 "KXETHD hourly THRESHOLD contract data"
call :capture_series KXSOL15M 15 "KXSOL15M contract data"
call :capture_series KXSOLD 60 "KXSOLD hourly THRESHOLD contract data (no range series exists for SOL)"
call :capture_series KXXRP15M 15 "KXXRP15M contract data"
call :capture_series KXXRP 60 "KXXRP hourly RANGE contract data"
call :capture_series KXXRPD 60 "KXXRPD hourly THRESHOLD contract data"

echo.
echo === %DATE% %TIME%  backfilling crypto-perp funding history (idempotent) ===
uv run python scripts\capture_session.py --backfill-funding --perp-asset all || echo *** step failed, continuing ***

echo.
echo === %DATE% %TIME%  polling 9 CF Benchmarks crypto indices for ~6 hours (Ctrl+C to stop) ===
uv run python scripts\capture_session.py --poll-brti --brti-source kalshi --brti-index all --interval 60 --duration 21600 || echo *** step failed, continuing ***

echo.
echo === %DATE% %TIME%  polling 9 crypto-perp settlement marks for ~3 hours (Ctrl+C to stop) ===
REM  Shorter than the BRTI poll: BRTI is the load-bearing feed for the current
REM  KXBTC15M validation, perp marks are ahead-of-need. Raise --duration here
REM  (up to match BRTI) once perp validation is the priority.
uv run python scripts\capture_session.py --poll-perp-marks --perp-asset all --interval 60 --duration 10800 || echo *** step failed, continuing (check for exchange ticker renumbering) ***

echo.
echo === %DATE% %TIME%  capturing current crypto-perp funding estimates ===
uv run python scripts\capture_session.py --capture-funding-estimates --perp-asset all || echo *** step failed, continuing ***

echo.
echo === %DATE% %TIME%  cycle done -- gap report ===
uv run python scripts\capture_session.py --report || echo *** step failed, continuing ***

REM advance the lookback window for the next cycle
for /f %%T in ('powershell -NoProfile -Command "[int][double]::Parse((Get-Date -UFormat %%s))"') do set NOW=%%T
set /a START=%NOW% - 259200
goto loop

REM ---------------------------------------------------------------------
REM  :capture_series <series_ticker> <period_minutes> <label>
REM  Skips the fetch if series_is_current.py says this series' candles
REM  already reach the current cycle's window end; otherwise captures it.
REM  Always continues to the caller's next line, even on failure.
REM ---------------------------------------------------------------------
:capture_series
set "_SERIES=%~1"
set "_PERIOD=%~2"
set "_LABEL=%~3"
uv run python scripts\series_is_current.py --series %_SERIES% --end-ts %NOW% --period %_PERIOD% >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo.
    echo === %DATE% %TIME%  %_LABEL%: already current for this window -- skipping ===
) else (
    echo.
    echo === %DATE% %TIME%  refreshing %_LABEL% ^(last 3 days^) ===
    uv run python scripts\capture_session.py --capture --series %_SERIES% --start-ts %START% --end-ts %NOW% || echo *** step failed, continuing ***
)
exit /b 0
