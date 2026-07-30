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
echo Appending new MarketPulse daily files...
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\append_database.py" %*
if errorlevel 1 (
  echo.
  echo Append failed. Read the message above. If needed, run Update_MarketPulse.bat for a full rebuild.
  pause
  exit /b 1
)
echo.
echo MarketPulse append update completed successfully.
pause
