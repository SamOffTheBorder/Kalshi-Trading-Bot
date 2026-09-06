@echo off
cd /d "%~dp0"
uv run python scripts\start_dashboard.py
pause
