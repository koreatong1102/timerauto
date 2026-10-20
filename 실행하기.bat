@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_release_env.ps1" -Install
if errorlevel 1 (
  pause
  exit /b 1
)
"%~dp0.venv-release\Scripts\python.exe" "%~dp0timerauto.py"
if errorlevel 1 pause
