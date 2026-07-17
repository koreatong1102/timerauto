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


def _ps_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _write_update_script(zip_path: str, app_dir: str, exe_path: str, process_id: int = 0) -> str:
    """Create a detached updater that waits for this exact app process."""
    script_path = os.path.join(tempfile.gettempdir(), "timerauto_apply_update.ps1")
    zip_path = os.path.abspath(zip_path)
    app_dir = os.path.abspath(app_dir)
    exe_path = os.path.abspath(exe_path)
    extract_dir = os.path.join(tempfile.gettempdir(), "TimerAutoUpdate", "extract")
    log_path = os.path.join(tempfile.gettempdir(), "TimerAutoUpdate", "apply.log")
    pid = max(0, int(process_id or 0))
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$zip = {_ps_quote(zip_path)}",
        f"$appDir = {_ps_quote(app_dir)}",
        f"$exePath = {_ps_quote(exe_path)}",
        f"$extractDir = {_ps_quote(extract_dir)}",
        f"$logPath = {_ps_quote(log_path)}",
        f"$processId = {pid}",
        "$logDir = Split-Path -Parent $logPath",
        "New-Item -ItemType Directory -Force -Path $logDir | Out-Null",
        "function Write-UpdateLog($text) { Add-Content -LiteralPath $logPath -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $text) }",
        "Set-Content -LiteralPath $logPath -Value ('==== TimerAuto update apply ' + (Get-Date) + ' ====')",
        "Write-UpdateLog ('zip=' + $zip)",
        "Write-UpdateLog ('app_dir=' + $appDir)",
        "Write-UpdateLog ('exe=' + $exePath)",
        "try {",
        "Start-Sleep -Seconds 2",
        "if ($processId -gt 0) {",
        "  $deadline = (Get-Date).AddSeconds(90)",
        "  while ((Get-Date) -lt $deadline -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500 }",
        "  if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw ('Timed out waiting for PID ' + $processId) }",
        "}",
        "Write-UpdateLog 'target process exited'",
        "if (Test-Path -LiteralPath $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }",
        "New-Item -ItemType Directory -Force -Path $extractDir | Out-Null",
        "Expand-Archive -LiteralPath $zip -DestinationPath $extractDir -Force",
        "Write-UpdateLog 'archive extracted'",
        "$protectedFiles = @('config.json','profile.json','profile1.json','as.json','test.json','latest.json')",
        "$protectedDirs = @('logs','image','ThrillOfTheFight2','TheThrillOfTheFight2','diagnostics','MatchLogArchive','SpectatorLogArchive')",
        "Get-ChildItem -LiteralPath $appDir -Force | Where-Object { $protectedFiles -notcontains $_.Name -and $protectedDirs -notcontains $_.Name } | Remove-Item -Recurse -Force",
        "Get-ChildItem -LiteralPath $extractDir -Force | Where-Object { $protectedFiles -notcontains $_.Name } | Copy-Item -Destination $appDir -Recurse -Force",
        "Write-UpdateLog 'application files replaced; user data preserved'",
        "Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue",
        "Start-Process -FilePath $exePath -WorkingDirectory $appDir",
        "Write-UpdateLog 'update apply completed'",
        "exit 0",
        "}",
        "catch { Write-UpdateLog ('update apply failed: ' + $_.Exception.Message); try { Start-Process -FilePath $exePath -WorkingDirectory $appDir } catch {}; exit 1 }",
    ]
    # Windows PowerShell 5.1 treats UTF-8 without a BOM as the active ANSI
    # codepage.  A BOM is required or Korean install paths become corrupted.
    with open(script_path, "w", encoding="utf-8-sig") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return script_path
