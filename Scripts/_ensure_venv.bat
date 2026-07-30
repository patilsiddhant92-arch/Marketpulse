@echo off
setlocal
set "ROOT=%~dp0.."
set "VENV=%ROOT%\.venv"
set "PY=%VENV%\Scripts\python.exe"
if exist "%PY%" goto :check

set "BUNDLED=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED%" (
  "%BUNDLED%" -m venv "%VENV%"
) else (
  py -3 -m venv "%VENV%"
)
if errorlevel 1 exit /b 1

:check
"%PY%" -c "import duckdb, nicegui, pandas, numpy, curl_cffi" >nul 2>nul
if not errorlevel 1 exit /b 0

:install
"%PY%" -m pip install -r "%ROOT%\Scripts\requirements.txt"
if errorlevel 1 exit /b 1
exit /b 0
