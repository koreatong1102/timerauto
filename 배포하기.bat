@echo off
cd /d "%~dp0"
echo TimerAuto release publish started.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0publish_release.ps1"
set "PUBLISH_EXIT=%ERRORLEVEL%"
echo.
if not "%PUBLISH_EXIT%"=="0" (
  echo Publish failed with exit code %PUBLISH_EXIT%. Check the error above.
) else (
  echo Publish completed. GitHub Actions will build the release.
)
pause
