@echo off
setlocal
cd /d "%~dp0"

echo.
echo Install MarketPulse Windows Task Scheduler job
echo   Name:     MarketPulse_EOD
echo   When:     Daily at 20:00 (8 PM local — use IST machine timezone)
echo   Action:   Run_MarketPulse_Auto.bat
echo   Retries:  if 8 PM fails, pipeline retries at +10 min and +20 min
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\install_schedule.ps1"
if errorlevel 1 (
  echo.
  echo Schedule install failed.
  pause
  exit /b 1
)

echo.
echo Done. Only three bats you need day-to-day:
echo   Launch_MarketPulse.bat          open the UI
echo   Run_MarketPulse_Auto.bat        download + append + Telegram (manual or scheduled)
echo   Install_MarketPulse_Schedule.bat  one-time: register 8 PM task
echo.
echo Emergency only:
echo   Rebuild_MarketPulse.bat         full rebuild from all Input history
echo.
echo Verify task:
echo   schtasks /Query /TN "MarketPulse_EOD" /V /FO LIST
echo.
echo Run once now:
echo   Run_MarketPulse_Auto.bat
echo.
pause
