@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Scripts\_ensure_venv.bat"
if errorlevel 1 (
  echo Setup failed. Read the message above.
  exit /b 1
)

echo.
echo MarketPulse automated EOD pipeline
echo   download latest NSE session + append database
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\daily_pipeline.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo Pipeline finished OK. See Database\status.json and Logs\pipeline_*.log
) else (
  echo Pipeline FAILED. See Database\status.json and Logs\pipeline_*.log
)

REM No pause — safe for Task Scheduler. For interactive use, read status.json.
exit /b %RC%
