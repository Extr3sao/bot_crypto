@echo off
REM ALPHA-002 derivatives capture wrapper.
REM
REM Binance keeps /futures/data/* for 30 days only; a missed run is data destroyed
REM for good.  This wrapper exists so the scheduled task needs no environment setup:
REM the driver already resolves its own repo root and sys.path.
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set "REPO=%~dp0.."
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
"%REPO%\.venv\Scripts\python.exe" "%~dp0alpha002_capture.py" >> "%REPO%\logs\alpha002_capture.log" 2>&1
exit /b %ERRORLEVEL%
