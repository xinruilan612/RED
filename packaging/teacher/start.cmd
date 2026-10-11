@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
if not exist "%~dp0python\python.exe" (
  echo The portable package is incomplete. Extract the whole ZIP first.
  pause
  exit /b 1
)
if not exist "%~dp0app\scripts\teacher_launcher.py" (
  echo The app folder is missing. Extract the whole ZIP first.
  pause
  exit /b 1
)
"%~dp0python\python.exe" -I -X utf8 -B "%~dp0app\scripts\teacher_launcher.py" %*
set "LAUNCH_RESULT=%ERRORLEVEL%"
echo.
echo Services stopped. Saved files remain in the data folder.
pause
exit /b %LAUNCH_RESULT%
