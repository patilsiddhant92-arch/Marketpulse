@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Scripts\_ensure_venv.bat"
if errorlevel 1 (
  echo.
  echo Setup failed. Read the message above.
  pause
  exit /b 1
)
echo This will download NSE archives (bhavcopy, all-index close, PR zip) since
echo 2020-01-01 into Input\archive\backfill\. This is a one-time backfill and
echo takes roughly 2.5-3 hours. It is safe to close this window and re-run it
echo later - the download resumes from where it left off. It does not touch
echo the MarketPulse database.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\run_archive_backfill.py" %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="2" (
  echo.
  echo Some files failed to download - network or NSE throttling. Run this file again to retry only the missing ones.
  pause
  exit /b 2
)
if not "%RC%"=="0" (
  echo.
  echo Backfill failed - exit code %RC%. Read the message above.
  pause
  exit /b %RC%
)
echo.
echo Backfill complete. Summary: Input\archive\backfill\last_run_summary.json
pause
