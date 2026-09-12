@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Scripts\_ensure_venv.bat"
if errorlevel 1 (
  echo Setup failed. Read the message above.
  pause
  exit /b 1
)

echo.
echo ===============================================================================
echo MarketPulse Daily Pipeline & Multi-Day Catch-Up
echo Automatically detects missing sessions, downloads NSE reports, and appends DB.
echo ===============================================================================
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\daily_pipeline.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo ===============================================================================
  echo Ingestion completed successfully! Check Database\status.json for details.
  echo ===============================================================================
) else (
  echo ===============================================================================
  echo Ingestion FAILED or interrupted (Exit code: %RC%). Check Logs\ for errors.
  echo ===============================================================================
)
echo.
pause
exit /b %RC%
