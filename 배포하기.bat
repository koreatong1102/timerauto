@echo off
cd /d "%~dp0"
echo TimerAuto release publish started.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_release.ps1"
echo.
if errorlevel 1 (
  echo Publish failed. Check the error above.
) else (
  echo Publish completed. GitHub Actions will build the release.
)
pause
