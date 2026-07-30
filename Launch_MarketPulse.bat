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

set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "APP=%ROOT%App\app.py"
set "URL=http://localhost:8080"

echo Starting MarketPulse at %URL%
start "MarketPulse Browser" /min powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$url = '%URL%'; $deadline = (Get-Date).AddSeconds(45);" ^
  "do { try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1 | Out-Null; Start-Process $url; exit 0 } catch { Start-Sleep -Milliseconds 700 } } while ((Get-Date) -lt $deadline)"

"%PY%" "%APP%"
echo.
echo MarketPulse stopped. Read any message above.
pause
