@echo off
REM Double-click this to open a visible archiver window.
REM Close the window anytime to stop -- every fetch is resumable, nothing is lost.
cd /d "%~dp0"
title Kalshi Archiver
uv run python scripts\archiver_loop.py
pause
