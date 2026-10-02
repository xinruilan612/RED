@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "runtime\venv\Scripts\python.exe" (
  "runtime\venv\Scripts\python.exe" "scripts\local_dev.py" %*
  goto finished
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "scripts\local_dev.py" %*
  goto finished
)
py -3.12 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
  py -3.12 "scripts\local_dev.py" %*
  goto finished
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
  py -3 "scripts\local_dev.py" %*
  goto finished
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
  python "scripts\local_dev.py" %*
  goto finished
)
echo Python 3.12 or newer is required. Install Python or prepare a project virtual environment.
set "YOUJI_EXIT=1"
goto finish_message
:finished
set "YOUJI_EXIT=%ERRORLEVEL%"
:finish_message
if not "%YOUJI_EXIT%"=="0" echo See docs\WINDOWS.md for setup instructions.
if not "%RED_NO_PAUSE%"=="1" pause
exit /b %YOUJI_EXIT%
