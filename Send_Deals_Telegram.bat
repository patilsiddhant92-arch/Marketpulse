@echo off
setlocal
cd /d "%~dp0"
call "%~dp0Scripts\_ensure_venv.bat"
if errorlevel 1 exit /b 1

echo.
echo MarketPulse - send deals TV lists to Telegram
echo.

if /I "%~1"=="--setup" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\telegram_deals.py" --setup
) else if /I "%~1"=="--dry-run" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\telegram_deals.py" --dry-run
) else (
  "%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\telegram_deals.py" %*
)

echo.
pause
