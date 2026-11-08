@echo off
setlocal
if not exist "%~dp0build_exe.bat" (
  echo [ERROR] Missing build_exe.bat next to this file.
  pause
  exit /b 1
)
call "%~dp0build_exe.bat" %*
exit /b %ERRORLEVEL%
