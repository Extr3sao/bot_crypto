@echo off
rem WP-051-02K — the observer's own cadence for the new campaign identity.
rem
rem The scheduler caps a task action at 261 characters, which is shorter than this command with
rem both roots named explicitly, so the registration points at this file and the roots live here.
rem The old registration named no roots and pointed at a checkout that no longer holds the
rem observer; it had been failing with exit 2 (python: can't open file) every fifteen minutes.
rem
rem Disabled until the frozen 15m shard is back: a tick without it dies at the frozen pin.
rem Re-enable with:  schtasks /change /tn TradingAgentic-EDGE04-Forward /enable

"%~dp0..\.venv\Scripts\python.exe" "%~dp0edge04_observer.py" --state-root "%~dp0..\data\forward\edge04r01" --store-root "%~dp0..\data\forward\edge03r01" --scheduled --due
