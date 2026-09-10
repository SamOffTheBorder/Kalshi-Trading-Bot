@echo off
REM ===========================================================================
REM  Kalshi Bot -- operator dashboard
REM ===========================================================================
REM  Double-click to open the dashboard in your browser. Close this window (or
REM  press Ctrl+C) to shut it down.
REM
REM  Read-only and safe: opening this dashboard NEVER starts trading. Trading
REM  always starts stopped, and no live-trading process exists yet in any case
REM  -- the Start button records operator intent only.
REM
REM  Binds to 127.0.0.1 (this machine only). Exposing it to the network
REM  requires DASHBOARD_AUTH_SECRET, since nothing here implements request
REM  auth yet.
REM
REM  Pages:
REM    Overview       trading control, validation readiness, capture health,
REM                   latest backtest, equity, recent decisions
REM    Data & capture feed freshness, BRTI sampling resolution, archive coverage
REM    Backtest runs  every recorded run and its evidence class
REM ===========================================================================

cd /d "%~dp0"
title Kalshi Bot Dashboard

echo.
echo   Kalshi Bot Dashboard
echo   --------------------
echo   Starting on http://127.0.0.1:8765/ (opens in your browser).
echo   Trading starts STOPPED. Close this window to shut down.
echo.

uv run python scripts\start_dashboard.py %*

REM Only reached if the server exits or fails to start -- keep the window open
REM so the error is readable instead of vanishing.
echo.
echo   Dashboard stopped.
pause
