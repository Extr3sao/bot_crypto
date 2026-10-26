@echo off
REM Read-only PAPER lab console (WP-SIGNAL-001/002): http://127.0.0.1:8787
REM
REM Loopback only, GET only. There is no endpoint that starts, stops, admits,
REM sizes or trades: the operator controls are printed on the page as commands.
setlocal
cd /d "%~dp0.."
uv run python scripts/paper_lab_dashboard.py --port 8787
