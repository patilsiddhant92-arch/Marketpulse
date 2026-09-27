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
set "PYTHONPATH=%ROOT%;%ROOT%App;%ROOT%Scripts"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "PORT=8000"
:find_free_port
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  set /a PORT+=1
  goto find_free_port
)
set "MP_PORT=%PORT%"
set "URL=http://127.0.0.1:%PORT%"

if not "%PORT%"=="8000" echo Port 8000 is busy; using %PORT% instead.

echo ======================================================================
echo 🚀 Starting MarketPulse 3.0 Terminal at %URL%
echo ======================================================================

start "MarketPulse Browser" /min powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$url = '%URL%'; $deadline = (Get-Date).AddSeconds(45);" ^
  "do { try { Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1 | Out-Null; Start-Process $url; exit 0 } catch { Start-Sleep -Milliseconds 700 } } while ((Get-Date) -lt $deadline)"

"%PY%" -m uvicorn App.api.server:app --host 127.0.0.1 --port %PORT%
echo.
echo MarketPulse 3.0 stopped. Read any message above.
pause
