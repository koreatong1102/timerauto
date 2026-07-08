# update_manager.py
# -*- coding: utf-8 -*-
"""Self-update helper functions for TimerAuto."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from typing import Any, Tuple
from urllib.request import Request, urlopen

def _parse_version(value: Any) -> Tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", str(value or ""))]
    return tuple(nums or [0])


def _download_file(url: str, dst: str) -> None:
    req = Request(url, headers={"User-Agent": "TimerAuto-Updater"})
    with urlopen(req, timeout=60) as resp, open(dst, "wb") as f:
        shutil.copyfileobj(resp, f)


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _write_update_script(zip_path: str, app_dir: str, exe_path: str) -> str:
    script_path = os.path.join(tempfile.gettempdir(), "timerauto_apply_update.bat")
    zip_path = os.path.abspath(zip_path)
    app_dir = os.path.abspath(app_dir)
    exe_path = os.path.abspath(exe_path)
    exe_name = os.path.basename(exe_path)
    extract_dir = os.path.join(tempfile.gettempdir(), "timerauto_update_extract")
    log_path = os.path.join(tempfile.gettempdir(), "timerauto_update_apply.log")
    lines = [
        "@echo off",
        "setlocal",
        f'set "UPDATE_LOG={log_path}"',
        'echo ==== TimerAuto update apply %DATE% %TIME% ==== > "%UPDATE_LOG%"',
        f'echo zip={zip_path} >> "%UPDATE_LOG%"',
        f'echo app_dir={app_dir} >> "%UPDATE_LOG%"',
        f'echo exe={exe_path} >> "%UPDATE_LOG%"',
        "timeout /t 2 /nobreak >nul",
        ":waitloop",
        f'tasklist /fi "imagename eq {exe_name}" | find /i "{exe_name}" >nul',
        "if not errorlevel 1 (",
        f'  echo waiting for {exe_name} to exit... >> "%UPDATE_LOG%"',
        "  timeout /t 1 /nobreak >nul",
        "  goto waitloop",
        ")",
        f'echo {exe_name} exited. >> "%UPDATE_LOG%"',
        f'if exist "{extract_dir}" rmdir /s /q "{extract_dir}"',
        f'mkdir "{extract_dir}"',
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''{zip_path}'' -DestinationPath ''{extract_dir}'' -Force" >> "%UPDATE_LOG%" 2>&1',
        "set EXPAND_CODE=%ERRORLEVEL%",
        'echo Expand-Archive exit=%EXPAND_CODE% >> "%UPDATE_LOG%"',
        'if not "%EXPAND_CODE%"=="0" goto fail',
        f'robocopy "{extract_dir}" "{app_dir}" /E /R:2 /W:1 /XD "{extract_dir}\\image\\players" >> "%UPDATE_LOG%" 2>&1',
        "set ROBO_CODE=%ERRORLEVEL%",
        'echo robocopy exit=%ROBO_CODE% >> "%UPDATE_LOG%"',
        "if %ROBO_CODE% GEQ 8 goto fail",
        f'rmdir /s /q "{extract_dir}"',
        'echo update apply completed. >> "%UPDATE_LOG%"',
        f'start "" "{exe_path}"',
        "endlocal",
        'del "%~f0"',
        "exit /b 0",
        ":fail",
        'echo update apply failed. >> "%UPDATE_LOG%"',
        f'start "" "{exe_path}"',
        "endlocal",
        "pause",
        "exit /b 1",
    ]
    with open(script_path, "w", encoding="mbcs", errors="ignore") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return script_path
