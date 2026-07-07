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
    lines = [
        "@echo off",
        "setlocal",
        "timeout /t 2 /nobreak >nul",
        ":waitloop",
        f'tasklist /fi "imagename eq {exe_name}" | find /i "{exe_name}" >nul',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto waitloop",
        ")",
        f'if exist "{extract_dir}" rmdir /s /q "{extract_dir}"',
        f'mkdir "{extract_dir}"',
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''{zip_path}'' -DestinationPath ''{extract_dir}'' -Force"',
        f'robocopy "{extract_dir}" "{app_dir}" /E /R:2 /W:1 /XD "{extract_dir}\\image\\players"',
        "if %ERRORLEVEL% GEQ 8 exit /b %ERRORLEVEL%",
        f'rmdir /s /q "{extract_dir}"',
        f'start "" "{exe_path}"',
        "endlocal",
        'del "%~f0"',
    ]
    with open(script_path, "w", encoding="mbcs", errors="ignore") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return script_path
