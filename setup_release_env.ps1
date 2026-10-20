param([switch]$Install)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = (Get-Content -LiteralPath (Join-Path $root ".python-version") -Raw).Trim()
$venvPython = Join-Path $root ".venv-release\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
  if (-not $Install) { throw "Run setup_release_env.ps1 -Install first." }
  $localPython = Join-Path $root ".runtime\python-$version\python.exe"
  if (Test-Path -LiteralPath $localPython) {
    & $localPython -m venv (Join-Path $root ".venv-release")
  } else {
    $currentPython = Get-Command python -ErrorAction SilentlyContinue
    $currentVersion = if ($currentPython) { & $currentPython.Source -c "import platform; print(platform.python_version())" } else { "" }
    if ($currentVersion -eq $version) {
      & $currentPython.Source -m venv (Join-Path $root ".venv-release")
    } else {
      py "-$version" -m venv (Join-Path $root ".venv-release")
    }
  }
  if ($LASTEXITCODE -ne 0) { throw "Install Python $version (64-bit), then retry." }
}
if ($Install) {
  & $venvPython (Join-Path $root "release_integrity.py") environment $root >$null
  if ($LASTEXITCODE -eq 0) { return }
  & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $root "requirements-release.lock")
  if ($LASTEXITCODE -ne 0) { throw "Locked dependency installation failed." }
}
& $venvPython (Join-Path $root "release_integrity.py") environment $root
if ($LASTEXITCODE -ne 0) { throw "Release environment validation failed." }
