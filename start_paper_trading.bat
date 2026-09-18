@echo off
REM ===========================================================================
REM  Kalshi Bot -- KXBTC15M paper trading loop
REM ===========================================================================
REM  Double-click to start. Close this window (or press Ctrl+C) to stop --
REM  every fill is written to the database immediately, so nothing is lost
REM  and open positions resume correctly next time you start this.
REM
REM  What it does, every ~5 seconds:
REM    1. polls live KXBTC15M quotes (unauthenticated Kalshi /markets)
REM    2. polls the live BRTI index (authenticated CF Benchmarks passthrough
REM       -- needs KALSHI_KEY_ID and secrets\kalshi_private_key.pem, same as
REM       start_capture.bat)
REM    3. evaluates the settlement-probability strategy
REM    4. on a BUY signal, places a LIMIT order (never a market/quick-buy) at
REM       the exact price the strategy's edge was computed against, sized by
REM       fixed-fractional risk
REM    5. settles paper positions when their market closes
REM
REM  NO REAL MONEY IS EVER AT RISK. No order this script places ever reaches
REM  Kalshi's order-entry API -- PaperBroker only records fills locally.
REM
REM  Watch it happen live on the dashboard: run start_dashboard.bat alongside
REM  this and open the Overview page -- Recent decisions and Equity curve
REM  update from the same database this loop writes to.
REM ===========================================================================

cd /d "%~dp0"
title Kalshi Bot -- Paper Trading (KXBTC15M)

echo.
echo   Kalshi Bot -- Paper Trading
echo   ---------------------------
echo   PAPER MODE. No real orders are ever sent to Kalshi.
echo   Close this window or press Ctrl+C to stop -- positions resume next run.
echo.

uv run python scripts\run_paper_trading.py %*

echo.
echo   Paper trading loop stopped.
pause
