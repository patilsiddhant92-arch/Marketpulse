@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Scripts\_ensure_venv.bat"
if errorlevel 1 (
  echo Setup failed. Read the message above.
  exit /b 1
)

echo.
echo MarketPulse EOD pipeline
echo   download NSE session + append DB + Telegram deals
echo   on failure: retry after 10 min (up to 3 attempts)
echo.
echo Examples:
echo   Run_MarketPulse_Auto.bat
echo   Run_MarketPulse_Auto.bat --date 06082026
echo   Run_MarketPulse_Auto.bat --append-only
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\daily_pipeline.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Pipeline finished OK. See Database\status.json and Logs\pipeline_*.log
) else (
  echo Pipeline FAILED after retries. See Database\status.json and Logs\pipeline_*.log
)

REM No pause — safe for Task Scheduler.
exit /b %RC%
