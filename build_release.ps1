param(
  [string]$Version = "",
  [switch]$SkipPip,
  [switch]$BuildInstaller,
  [switch]$NoZip,
  [switch]$IncludeUserConfig,
  [switch]$IncludePlayerImages
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Get-SourceSnapshot {
  $snapshot = [ordered]@{}
  foreach ($file in (Get-ChildItem -LiteralPath $root -File | Where-Object { $_.Extension -in @('.py', '.qml', '.spec', '.lock') -or $_.Name -eq '.python-version' } | Sort-Object Name)) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($file.FullName)
    try { $snapshot[$file.Name] = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
  }
  return ($snapshot | ConvertTo-Json -Compress)
}

if ([string]::IsNullOrWhiteSpace($Version)) {
  $source = Get-Content -LiteralPath (Join-Path $root "timerauto.py") -Raw -Encoding UTF8
  $match = [regex]::Match($source, 'APP_VERSION\s*=\s*["'']([^"'']+)["'']')
  if (-not $match.Success) {
    throw "APP_VERSION was not found in timerauto.py"
  }
  $Version = $match.Groups[1].Value
}

Write-Host "Preparing release build (version: $Version)"

$releaseDir = Join-Path $root "release"
if (-not (Test-Path $releaseDir)) {
  New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
}

if (-not $SkipPip) {
  & (Join-Path $root "setup_release_env.ps1") -Install
}
$python = Join-Path $root ".venv-release\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Missing release environment. Run setup_release_env.ps1 -Install." }
& $python (Join-Path $root "release_integrity.py") environment $root
if ($LASTEXITCODE -ne 0) { throw "Release environment mismatch." }
& $python -m unittest discover -s tests -p "test_*.py"
if ($LASTEXITCODE -ne 0) { throw "Release unit tests failed." }
$sourceCheck = Join-Path $releaseDir "parity-source.json"
$sourceSnapshot = Get-SourceSnapshot
& $python timerauto.py --release-self-test --output $sourceCheck
if ($LASTEXITCODE -ne 0) { throw "Source self-test failed. See $sourceCheck" }

Write-Host "Building with PyInstaller..."
if ($IncludeUserConfig) { $env:TIMERAUTO_INCLUDE_USER_CONFIG = "1" } else { Remove-Item Env:TIMERAUTO_INCLUDE_USER_CONFIG -ErrorAction SilentlyContinue }
if ($IncludePlayerImages) { $env:TIMERAUTO_INCLUDE_PLAYER_IMAGES = "1" } else { Remove-Item Env:TIMERAUTO_INCLUDE_PLAYER_IMAGES -ErrorAction SilentlyContinue }
$buildDir = Join-Path $root "build\timerauto"
$distDir = Join-Path $root "dist\timerauto"
foreach ($dir in @($buildDir, $distDir)) {
  if (Test-Path $dir) {
    Remove-Item -LiteralPath $dir -Recurse -Force
  }
}
# Native dependency scanning must not borrow DLLs from unrelated tools in PATH
# (for example Poppler's icuuc.dll is incompatible with Windows' ICU API).
$originalBuildPath = $env:PATH
$nativeEnvironment = @{}
foreach ($name in @('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH')) {
  $nativeEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
try {
  $basePython = (& $python -c "import sys; print(sys.base_prefix)").Trim()
  $env:PATH = @((Split-Path -Parent $python), $basePython, (Join-Path $basePython 'DLLs'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
  & $python -m PyInstaller --clean timerauto.spec
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
} finally {
  $env:PATH = $originalBuildPath
  foreach ($name in $nativeEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $nativeEnvironment[$name], 'Process') }
}
if ($sourceSnapshot -ne (Get-SourceSnapshot)) { throw "Source files changed during build. Retry from a stable source snapshot." }

$dist = Join-Path $root "dist\\timerauto"
if (-not (Test-Path $dist)) {
  throw "dist\\timerauto not found. Build may have failed."
}

Write-Host "Syncing runtime data into dist..."
$files = @(
  "HELP.md",
  "SIMPLE_MANUAL.md",
  "timer_ui.qml",
  "cinematic_overlay.qml",
  "timer_controls.qml"
)
if ($IncludeUserConfig) {
  $files += @(
    "config.json",
    "profile.json"
  )
}

foreach ($f in $files) {
  $src = Join-Path $root $f
  if (Test-Path $src) {
    Copy-Item -Force $src $dist
  }
}

# Remove legacy sound-detection files if this dist folder was reused.
$legacySoundFiles = @(
  "sound_actions.json",
  "sound_templates.json",
  "sound_events.jsonl",
  "sound_engine.py",
  "소리감지.py"
)
foreach ($f in $legacySoundFiles) {
  $legacy = Join-Path $dist $f
  if (Test-Path $legacy) {
    Remove-Item -Force $legacy
  }
}

function Get-RelPath([string]$root, [string]$src) {
  try {
    return [IO.Path]::GetRelativePath($root, $src)
  } catch {
    $rootFull = (Resolve-Path $root).Path
    $srcFull = (Resolve-Path $src).Path
    $rootUri = New-Object System.Uri(($rootFull.TrimEnd('\') + '\'))
    $srcUri = New-Object System.Uri($srcFull)
    $relUri = $rootUri.MakeRelativeUri($srcUri)
    $rel = [System.Uri]::UnescapeDataString($relUri.ToString()) -replace '/', '\'
    return $rel
  }
}

function Copy-RelativeFile([string]$src, [string]$root, [string]$dist) {
  $rel = Get-RelPath $root $src
  $dst = Join-Path $dist $rel
  $dir = Split-Path -Parent $dst
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  Copy-Item -Force $src $dst
}

# Ship reviewed project media only, never recordings, diagnostics or venv files.
$trackedMedia = @(git -c core.quotepath=false ls-files)
if ($LASTEXITCODE -ne 0) { throw "Unable to enumerate release assets." }
foreach ($relative in $trackedMedia) {
  if ([IO.Path]::GetExtension($relative).ToLowerInvariant() -notin @(".mp3", ".wav", ".mp4", ".webm", ".mov", ".m4v", ".avi", ".ogv", ".ogg", ".png", ".jpg", ".jpeg", ".bmp")) { continue }
  if (-not $IncludePlayerImages -and $relative.Replace('\', '/').StartsWith('image/players/')) { continue }
  Copy-RelativeFile (Join-Path $root $relative) $root $dist
}
# Also support validating newly added venue assets before they are Git-staged.
foreach ($venueImage in @('home_gym.png', 'night_gym.jpg', 'hotel.png', 'memorial_hall.png', 'philly_parkway.jpg')) {
  Copy-RelativeFile (Join-Path $root "assets/images/venues/$venueImage") $root $dist
}

# Ensure SFX referenced by config are present even if stored elsewhere
$cfgPath = Join-Path $root "config.json"
if ($IncludeUserConfig -and (Test-Path $cfgPath)) {
  try {
    $cfg = Get-Content -Raw $cfgPath | ConvertFrom-Json
    $sfxPaths = @()
    if ($cfg.win_effects -and $cfg.win_effects.burst -and $cfg.win_effects.burst.sfx_path) {
      $sfxPaths += $cfg.win_effects.burst.sfx_path
    }
    if ($cfg.win_effects -and $cfg.win_effects.fail -and $cfg.win_effects.fail.sfx_path) {
      $sfxPaths += $cfg.win_effects.fail.sfx_path
    }
    if ($cfg.win_effects -and $cfg.win_effects.nameplates -and $cfg.win_effects.nameplates.images) {
      foreach ($np in $cfg.win_effects.nameplates.images) {
        if ($np) { $sfxPaths += $np }
      }
    }
    foreach ($p in $sfxPaths) {
      if (-not $p) { continue }
      $src = $p
      if (-not [System.IO.Path]::IsPathRooted($src)) {
        $src = Join-Path $root $src
      }
      if (Test-Path $src) {
        Copy-RelativeFile $src $root $dist
      }
    }
  } catch {
    Write-Host "Warning: failed to parse config.json for SFX paths."
  }
}

@(
  "logs",
  "__pycache__",
  "백업",
  "backup",
  ".git",
  ".github",
  ".vscode",
  ".codex",
  ".agents"
) | ForEach-Object {
  $junk = Join-Path $dist $_
  if (Test-Path $junk) {
    Remove-Item -LiteralPath $junk -Recurse -Force
  }
}

Get-ChildItem -Path $dist -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $dist -Recurse -Include "*.pyc", "*.pyo", "*.log", "*.jsonl" -File -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
if (-not $IncludeUserConfig) {
  foreach ($localFile in @("config.json", "profile.json", "profile1.json", "as.json", "test.json", "latest.json")) {
    $p = Join-Path $dist $localFile
    if (Test-Path $p) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }
  }

  # Public release first-run defaults.  Do not copy SWa's absolute paths, but do
  # ship a tiny sanitized config so another user can press Start and immediately
  # use SpectatorLog auto-discovery.
  $releaseCfg = [ordered]@{
    spectatorlog_enabled = $true
    spectatorlog_path = ""
    spectatorlog_sync_timer = $true
    spectatorlog_sync_players = $true
    spectatorlog_file_watch_enabled = $true
    spectatorlog_poll_ms = 150
    spectatorlog_backup_poll_ms = 1500
    obs_replay_transition_enabled = $true
    obs_replay_transition_before_path = "assets\\video\\logo.webm"
    obs_replay_transition_after_path = "assets\\video\\logo.webm"
    obs_replay_transition_test_video_path = "assets\\video\\logo.webm"
    spectator_commentary_enabled = $true
    spectator_commentary_mode = "standard"
    spectator_commentary_voice = "ko-KR-InJoonNeural"
    spectator_caster_voice = "ko-KR-SunHiNeural"
    qml_preview_enabled = $true
    browser_overlay_output_only = $true
    overlay_ui_bg_opacity = 0.75
    portrait_source_priority = "log"
  }
  $releaseCfgPath = Join-Path $dist "config.json"
  $releaseCfg | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $releaseCfgPath -Encoding UTF8
}

# Release sanity checks for another user's PC.
$requiredReleaseFiles = @(
  "timerauto.exe",
  "HELP.md",
  "SIMPLE_MANUAL.md",
  "timer_ui.qml",
  "cinematic_overlay.qml",
  "timer_controls.qml",
  "assets\\images\\overlays\\KD.png",
  "assets\\images\\overlays\\TKO.png",
  "assets/images/venues/home_gym.png",
  "assets/images/venues/night_gym.jpg",
  "assets/images/venues/hotel.png",
  "assets/images/venues/memorial_hall.png",
  "assets/images/venues/philly_parkway.jpg"
)
foreach ($required in $requiredReleaseFiles) {
  $requiredPath = Join-Path $dist $required
  if (-not (Test-Path $requiredPath)) {
    throw "release missing required file: $required"
  }
}

if ($IncludeUserConfig) {
  $distCfg = Join-Path $dist "config.json"
  if (Test-Path $distCfg) {
    $cfgText = Get-Content -Raw -LiteralPath $distCfg -ErrorAction SilentlyContinue
    if ($cfgText -match "C:\\Users\\" -or $cfgText -match "/Users/" -or $cfgText -match "/mnt/") {
      Write-Warning "Included config.json appears to contain machine-specific absolute paths. For public release, prefer default build without -IncludeUserConfig or clean paths first."
    }
  }
}

& $python release_integrity.py create $root $dist $Version
if ($LASTEXITCODE -ne 0) { throw "Release manifest creation failed." }
$frozenCheck = Join-Path $releaseDir "parity-frozen.json"
if (Test-Path -LiteralPath $frozenCheck) { Remove-Item -LiteralPath $frozenCheck -Force }
$exe = Join-Path $dist "timerauto.exe"
$checkArgs = '--release-self-test --output "{0}" --expected "{1}" --verify-package' -f $frozenCheck, $sourceCheck
$checkProcess = Start-Process -FilePath $exe -ArgumentList $checkArgs -WorkingDirectory $dist -WindowStyle Hidden -PassThru
if (-not $checkProcess.WaitForExit(120000)) {
  Stop-Process -Id $checkProcess.Id -Force
  throw "Frozen self-test timed out."
}
if ($checkProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $frozenCheck)) { throw "Frozen/source parity failed. See $frozenCheck" }
$checkResult = Get-Content -LiteralPath $frozenCheck -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $checkResult.ok) { throw "Frozen/source parity failed. See $frozenCheck" }
Write-Host "Verified: source and frozen runtime, verdicts, reports and assets match."

$portableZip = Join-Path $releaseDir ("TimerAuto_v{0}_portable.zip" -f $Version)
if (-not $NoZip) {
  if (Test-Path $portableZip) {
    Remove-Item -LiteralPath $portableZip -Force
  }
  Write-Host "Creating portable zip: $portableZip"
  Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $portableZip -Force

  $latestTemplate = [ordered]@{
    version = $Version
    url = "https://example.com/TimerAuto_v$Version`_portable.zip"
    notes = "TimerAuto $Version"
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $portableZip).Hash.ToLowerInvariant()
  }
  $latestPath = Join-Path $releaseDir "latest.template.json"
  $latestTemplate | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $latestPath -Encoding UTF8
  Write-Host "Wrote update metadata template: $latestPath"
}

Write-Host "Done. Portable folder: dist\\timerauto"
if (-not $NoZip) {
  Write-Host "Done. Portable zip: $portableZip"
}

if ($BuildInstaller) {
  $iss = Join-Path $root "installer\\TimerAuto.iss"
  if (-not (Test-Path $iss)) {
    throw "installer\\TimerAuto.iss not found."
  }
  $iscc = Get-Command iscc -ErrorAction SilentlyContinue
  if (-not $iscc) {
    Write-Warning "Inno Setup compiler (iscc) not found. Skipping installer build."
    exit 0
  }
  Write-Host "Building installer with Inno Setup..."
  & $iscc.Source "/DTimerAutoVersion=$Version" $iss
  Write-Host "Installer build complete."
}
