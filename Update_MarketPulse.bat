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
if "%*"=="" (
  echo Updating MarketPulse database using daily files...
  "%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\daily_update.py"
) else (
  echo Updating MarketPulse database using daily files with arguments: %*
  "%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\daily_update.py" %*
)
if errorlevel 1 (
  echo.
  echo Update failed. Read the message above.
  pause
  exit /b 1
)
echo.
echo MarketPulse database updated successfully.
echo.
echo NOTE: If you missed daily file uploads on some days, drop the missed bhavcopy*.csv / bulk / block / mcap / 52wk / etc files (with their original dates in filenames) into Input\daily\ and run the FULL builder directly:
echo   python Scripts\build_database.py
echo This always does a complete rebuild from all history in archive + daily (preserves consistency).
pause
