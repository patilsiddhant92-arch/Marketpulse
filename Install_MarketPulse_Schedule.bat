@echo off
setlocal
cd /d "%~dp0"

echo.
echo Install MarketPulse Windows Task Scheduler job
echo   Name:     MarketPulse_EOD
echo   When:     Daily at 20:00 (8 PM local time — use IST machine timezone)
echo   Action:   Run_MarketPulse_Auto.bat
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\install_schedule.ps1"
if errorlevel 1 (
  echo.
  echo Schedule install failed.
  pause
  exit /b 1
)

echo.
echo Done. To verify:
echo   schtasks /Query /TN "MarketPulse_EOD" /V /FO LIST
echo.
echo To remove later:
echo   schtasks /Delete /TN "MarketPulse_EOD" /F
echo.
echo To run once now without waiting for 8 PM:
echo   Run_MarketPulse_Auto.bat
echo.
pause
