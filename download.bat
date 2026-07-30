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

echo Downloading NSE daily reports...
echo   Interactive date picker by default.
echo   For unattended: download.bat --auto
echo   Full auto EOD (download+append at 8 PM): Run_MarketPulse_Auto.bat
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\download_nse_reports.py" %*
if errorlevel 1 (
  echo.
  echo Download failed. Read the message above.
  pause
  exit /b 1
)

echo.
echo NSE daily files are ready in Input\daily.
echo Next step when ready:
echo   Append_MarketPulse.bat
echo Or one-shot automation:
echo   Run_MarketPulse_Auto.bat
pause
