# update_manager.py
# -*- coding: utf-8 -*-
"""Self-update helper functions for TimerAuto."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import uuid
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
    operation = uuid.uuid4().hex
    script_path = os.path.join(tempfile.gettempdir(), f"timerauto_apply_update_{operation}.ps1")
    zip_path = os.path.abspath(zip_path)
    app_dir = os.path.abspath(app_dir)
    exe_path = os.path.abspath(exe_path)
    extract_dir = os.path.join(tempfile.gettempdir(), "TimerAutoUpdate", "extract_" + operation)
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
        "$backupDir = Join-Path (Split-Path -Parent $appDir) ('.timerauto-backup-' + [guid]::NewGuid().ToString('N'))",
        "$moved = @(); $installed = @()",
        "$logDir = Split-Path -Parent $logPath",
        "New-Item -ItemType Directory -Force -Path $logDir | Out-Null",
        "function Write-UpdateLog($text) { Add-Content -LiteralPath $logPath -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $text) }",
        "function Assert-Child($root, $path) { if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($path)) -ne [IO.Path]::GetFullPath($root).TrimEnd('\\')) { throw ('Unsafe update target: ' + $path) } }",
        "function Get-ReleaseHash($path) { $sha = [Security.Cryptography.SHA256]::Create(); $stream = [IO.File]::OpenRead($path); try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() } finally { $stream.Dispose(); $sha.Dispose() } }",
        "function Assert-Package($root) {",
        "  $manifest = Get-Content -LiteralPath (Join-Path $root 'release_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json",
        "  if ($manifest.schema -ne 1 -or -not $manifest.files.'timerauto.exe') { throw 'Invalid release manifest' }",
        "  $prefix = [IO.Path]::GetFullPath($root).TrimEnd('\\') + '\\'",
        "  foreach ($entry in $manifest.files.PSObject.Properties) {",
        "    $rel = $entry.Name",
        "    if ($rel -match '(^/|\\\\|:|(^|/)\\.\\.(/|$))') { throw 'Unsafe manifest path' }",
        "    $path = [IO.Path]::GetFullPath((Join-Path $root $rel))",
        "    if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest escapes package' }",
        "    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Missing release file: ' + $rel) }",
        "    if ((Get-Item -LiteralPath $path).Length -ne $entry.Value.size -or (Get-ReleaseHash $path) -ne $entry.Value.sha256) { throw ('Release hash mismatch: ' + $rel) }",
        "  }",
        "  return $manifest",
        "}",
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
        "New-Item -ItemType Directory -Force -Path $extractDir | Out-Null",
        "Expand-Archive -LiteralPath $zip -DestinationPath $extractDir -Force",
        "Write-UpdateLog 'archive extracted'",
        "$manifest = Assert-Package $extractDir",
        "Write-UpdateLog ('staged package verified commit=' + $manifest.commit)",
        "$protectedFiles = @('config.json','profile.json','profile1.json','as.json','test.json','latest.json')",
        "$protectedDirs = @('logs','image','ThrillOfTheFight2','TheThrillOfTheFight2','diagnostics','MatchLogArchive','SpectatorLogArchive')",
        "$roots = @($manifest.files.PSObject.Properties.Name | ForEach-Object { ($_ -split '/')[0] }) + @('release_manifest.json')",
        "$oldManifest = Join-Path $appDir 'release_manifest.json'",
        "if (Test-Path -LiteralPath $oldManifest) { $old = Get-Content -LiteralPath $oldManifest -Raw -Encoding UTF8 | ConvertFrom-Json; $roots += @($old.files.PSObject.Properties.Name | ForEach-Object { ($_ -split '/')[0] }) }",
        "$roots = @($roots | Sort-Object -Unique)",
        "foreach ($name in $roots) {",
        "  if ($protectedFiles -contains $name -or $protectedDirs -contains $name) { throw ('Release attempts to replace user data: ' + $name) }",
        "  Assert-Child $appDir (Join-Path $appDir $name)",
        "}",
        "Assert-Child (Split-Path -Parent $appDir) $backupDir",
        "New-Item -ItemType Directory -Path $backupDir | Out-Null",
        "foreach ($name in $roots) {",
        "  $target = Join-Path $appDir $name",
        "  if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination (Join-Path $backupDir $name); $moved += $name }",
        "  $source = Join-Path $extractDir $name",
        "  if (Test-Path -LiteralPath $source) { $installed += $name; Copy-Item -LiteralPath $source -Destination $target -Recurse -Force }",
        "}",
        "$verified = Assert-Package $appDir",
        "Write-UpdateLog ('installed package verified commit=' + $verified.commit)",
        "Write-UpdateLog 'application files replaced; user data preserved'",
        "Start-Process -FilePath $exePath -WorkingDirectory $appDir",
        "Assert-Child (Split-Path -Parent $appDir) $backupDir",
        "Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue",
        "Assert-Child (Split-Path -Parent $extractDir) $extractDir",
        "Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue",
        "Write-UpdateLog 'update apply completed'",
        "exit 0",
        "}",
        "catch {",
        "  Write-UpdateLog ('update apply failed: ' + $_.Exception.Message)",
        "  try {",
        "    foreach ($name in $installed) { $target = Join-Path $appDir $name; Assert-Child $appDir $target; if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force } }",
        "    foreach ($name in $moved) { $target = Join-Path $appDir $name; Assert-Child $appDir $target; Move-Item -LiteralPath (Join-Path $backupDir $name) -Destination $target }",
        "    Write-UpdateLog 'previous version restored'",
        "    Start-Process -FilePath $exePath -WorkingDirectory $appDir",
        "  } catch { Write-UpdateLog ('rollback requires recovery from ' + $backupDir + ': ' + $_.Exception.Message) }",
        "  exit 1",
        "}",
    ]
    # Windows PowerShell 5.1 treats UTF-8 without a BOM as the active ANSI
    # codepage.  A BOM is required or Korean install paths become corrupted.
    with open(script_path, "w", encoding="utf-8-sig") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return script_path
