@echo off
REM ALPHA-002 derivatives capture wrapper.
REM
REM Binance keeps /futures/data/* for 30 days only; a missed run is data destroyed
REM for good.  This wrapper exists so the scheduled task needs no environment setup:
REM the driver already resolves its own repo root and sys.path.
REM
REM The task must not draw a console: it runs under an interactive principal, so a
REM console interpreter here would own a visible window for the whole capture.
REM pythonw.exe has no console of its own and windowless.py starts the real
REM interpreter with CREATE_NO_WINDOW, keeping stdout/stderr in the log and the
REM child's exit code as this script's exit code.
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set "REPO=%~dp0.."
if not exist "%REPO%\logs" mkdir "%REPO%\logs"
"%REPO%\.venv\Scripts\pythonw.exe" "%REPO%\scripts\windowless.py" ^
  --log "%REPO%\logs\alpha002_capture.log" ^
  --event-log "%REPO%\logs\alpha002_capture.execution.jsonl" ^
  --label alpha002_capture ^
  --keep-together ^
  -- "%REPO%\.venv\Scripts\python.exe" "%~dp0alpha002_capture.py"
exit /b %ERRORLEVEL%
