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
echo Rebuilding MarketPulse from all validated input history...
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\build_database.py" %*
if errorlevel 1 (
  echo.
  echo Full rebuild failed. The accepted database was not replaced unless validation completed.
  pause
  exit /b 1
)
echo.
echo MarketPulse full rebuild completed successfully.
pause
