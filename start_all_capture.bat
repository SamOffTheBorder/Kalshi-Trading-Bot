@echo off
REM ===========================================================================
REM  ALL-DOMAIN data capture  (multi-venue-paper-trading)
REM ===========================================================================
REM  One window that fills every data category the paper programme needs.
REM  Double-click to run. Close it anytime to stop -- every phase is resumable
REM  and idempotent, so nothing is lost and re-running never duplicates rows.
REM
REM  It never schedules itself and never runs unattended. This is a foreground
REM  window you start and stop by hand.
REM
REM  PHASE 1 (once, then skipped)  BACKFILLABLE HISTORY -- no waiting
REM    * Binance monthly archives: BTC/ETH/SOL/XRP, spot + USD-M perp, 1m bars,
REM      checksum-verified. This is the PRIMARY source every promotion gate
REM      reads. Years of history are downloadable immediately.
REM    * Kalshi crypto-series discovery (unauthenticated).
REM    * Kalshi sports discovery for the per-game two-outcome series.
REM
REM  PHASE 2 (loops)  LIVE-ONLY FEEDS -- these only advance while this runs
REM    * markets + contract candles for BTC/ETH/SOL/XRP's 15-minute and hourly
REM      event series -- last 3 days, unauthenticated. Kalshi runs TWO
REM      distinct hourly series per asset that both close on the hour: a
REM      THRESHOLD ladder (KX{A}D, "above $X") and a RANGE ladder (KX{A},
REM      "between $X and $Y", strike_type=between) -- zero ticker overlap
REM      between them. Both are captured for BTC/ETH/XRP. SOL has no range
REM      series on the exchange (KXSOL/KXSOLRANGE return 0 markets) so it
REM      only has KXSOL15M + KXSOLD:
REM        KXBTC15M, KXBTC   (range),  KXBTCD  (threshold)
REM        KXETH15M, KXETH   (range),  KXETHD  (threshold)
REM        KXSOL15M,                   KXSOLD  (threshold; no range exists)
REM        KXXRP15M, KXXRP   (range),  KXXRPD  (threshold)
REM    * crypto-perp funding history (backfillable, idempotent each cycle)
REM    * 9 CF Benchmarks crypto indices for ~6h (authenticated passthrough)
REM    * 9 crypto-perp settlement marks for ~3h (authenticated, read-only)
REM    * KXBTC15M order-book snapshots for ~3h (unauthenticated, feeds the
REM      microprice experiment -- strategy/experiments.py)
REM    * KXBTC15M public trades for ~3h (unauthenticated, feeds the
REM      public_trade_imbalance experiment)
REM    * current funding estimates (one snapshot; not backfillable)
REM
REM  The BRTI/perp-mark windows are the long pole: Kalshi publishes no history
REM  for them, so the only way to reach the ~90 day validation target is wall
REM  clock time with this window open.
REM
REM  Authenticated phases need KALSHI_KEY_ID and secrets\kalshi_private_key.pem.
REM  Everything in phase 1 works without credentials.
REM
REM  To change the Binance history depth, edit BINANCE_START below.
REM ===========================================================================

cd /d "%~dp0"
title All-domain capture  (Binance history + Kalshi live feeds)

REM ---- how far back to pull Binance monthly archives -----------------------
set BINANCE_START=2025-01
set BINANCE_END=2026-08

REM ---- sports series to discover (per-game, two-outcome only) --------------
set SPORTS_SERIES=KXNFLGAME,KXNBAGAME,KXNHLGAME,KXMLBGAME,KXNCAAFGAME,KXNCAABGAME,KXEPLGAME,KXUCLGAME,KXATPMATCH,KXWTAMATCH,KXWNBAGAME,KXUFCFIGHT

echo.
echo ==========================================================
echo  PHASE 1/2  backfillable history (runs once, then skips)
echo ==========================================================

echo.
echo === %DATE% %TIME%  Binance monthly archives %BINANCE_START% .. %BINANCE_END% ===
echo     BTC/ETH/SOL/XRP x spot+perp. Already-imported months are skipped.
uv run python scripts\backfill_binance.py --start %BINANCE_START% --end %BINANCE_END%

echo.
echo === %DATE% %TIME%  Kalshi crypto-series discovery ===
uv run python scripts\discover_crypto_series.py

echo.
echo === %DATE% %TIME%  Kalshi sports discovery ===
uv run python scripts\capture_sports.py --series %SPORTS_SERIES% --discover

echo.
echo ==========================================================
echo  PHASE 2/2  live-only feeds (loops until you close this)
echo ==========================================================

REM 3-day lookback for the contract-candle refresh, in epoch seconds.
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
echo === %DATE% %TIME%  refreshing sports discovery snapshot ===
uv run python scripts\capture_sports.py --series %SPORTS_SERIES% --discover

echo.
echo === %DATE% %TIME%  polling 9 CF Benchmarks crypto indices for ~6 hours ===
uv run python scripts\capture_session.py --poll-brti --brti-source kalshi --brti-index all --interval 60 --duration 21600

echo.
echo === %DATE% %TIME%  polling 9 crypto-perp settlement marks for ~3 hours ===
uv run python scripts\capture_session.py --poll-perp-marks --perp-asset all --interval 60 --duration 10800

echo.
echo === %DATE% %TIME%  polling KXBTC15M order books for ~3 hours (microprice) ===
uv run python scripts\capture_session.py --poll-l2 --l2-series KXBTC15M --interval 15 --duration 10800

echo.
echo === %DATE% %TIME%  polling KXBTC15M public trades for ~3 hours (trade imbalance) ===
uv run python scripts\capture_session.py --poll-trades --trades-series KXBTC15M --interval 15 --duration 10800

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
