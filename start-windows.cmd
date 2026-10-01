@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist "runtime\venv\Scripts\python.exe" (
  "runtime\venv\Scripts\python.exe" "scripts\local_dev.py" %*
) else (
  py -3.12 "scripts\local_dev.py" %*
)
set "YOUJI_EXIT=%ERRORLEVEL%"
if not "%YOUJI_EXIT%"=="0" echo See docs\WINDOWS.md for setup instructions.
pause
exit /b %YOUJI_EXIT%
