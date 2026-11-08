@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0build_release.ps1" (
  echo [ERROR] Missing build_release.ps1. Keep this file in the source folder.
  pause
  exit /b 1
)
if /I "%~1"=="/check" (
  echo [OK] Build launcher and source path are valid. No build was started.
  exit /b 0
)
echo Building TimerAuto EXE. Keep this window open until it finishes.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"
echo.
if not "%BUILD_EXIT%"=="0" (
  echo [FAILED] The build did not complete. Read the error above.
) else (
  echo [OK] EXE: "%~dp0dist\timerauto\timerauto.exe"
  echo [OK] ZIP folder: "%~dp0release"
)
pause
exit /b %BUILD_EXIT%
