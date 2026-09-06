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
echo Fetching latest bulk and block deals from NSE and refreshing MarketPulse database...
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\refresh_deals.py" --fetch
if errorlevel 1 (
  echo.
  echo Deals refresh failed. Read the message above.
  pause
  exit /b 1
)
echo.
echo MarketPulse deals refresh completed successfully.
pause
