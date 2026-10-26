@echo off
REM Portable Windows 11 start/restart for the always-on PAPER lab (WP-SIGNAL-003).
REM
REM   scripts\paper_lab_service.cmd [run-id]
REM
REM The lab supervises its own children (PAPER, collector, retention, strategy lab,
REM AI analyst) and restarts each one independently. This wrapper adds the other
REM half of "always on": it restarts the *lab* with the same run id, so a host
REM reboot or a crashed supervisor continues the same evidence rather than
REM starting a second, unrelated run.
REM
REM The analyst key is not read here: scripts\paper_lab_service.py decrypts it with
REM DPAPI (current user) straight into the child's environment, so this wrapper and
REM the task that calls it never hold or print a credential.
REM
REM It holds no credentials, opens no exchange position and cannot reach LIVE:
REM every child is read-only market data or the PAPER broker.
setlocal
cd /d "%~dp0.."

set RUN_ID=%~1
if "%RUN_ID%"=="" set RUN_ID=paper-lab-service

echo [service] run id: %RUN_ID%
echo [service] root  : %CD%
echo [service] stop  : write STOP into reports\paper-lab\%RUN_ID%, or scripts\paper_lab_service.cmd --stop
echo [service] view  : scripts\paper_lab_dashboard.cmd  (http://127.0.0.1:8787)
echo [service] key   : python scripts\paper_lab_service.py --secret-status

if "%~1"=="--stop" goto :stop

uv run python scripts/paper_lab_service.py --run-id %RUN_ID%
exit /b %ERRORLEVEL%

:stop
uv run python scripts/paper_lab_service.py --run-id %RUN_ID% --stop
exit /b %ERRORLEVEL%
