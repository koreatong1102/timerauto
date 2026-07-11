param(
  [string]$CommitMessage = "chore: publish TimerAuto update",
  [switch]$SkipChecks,
  [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Assert-CommandSuccess([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE."
  }
}

$branch = (git branch --show-current).Trim()
if (-not $branch) {
  throw "No active Git branch was found."
}
Write-Host "Current branch: $branch"

if (-not $SkipChecks) {
  Write-Host "Running validation..."
  python -m unittest discover -s tests -p "test_*.py"
  Assert-CommandSuccess "Unit tests"
  python -m py_compile timerauto.py update_manager.py spectator_log_watcher.py browser_overlay.py
  Assert-CommandSuccess "Python compile check"
  git diff --check
  Assert-CommandSuccess "Git diff check"
}

Write-Host "Staging tracked and new project files..."
git add -A
Assert-CommandSuccess "Git staging"

$staged = git diff --cached --name-only
if (-not $staged) {
  Write-Host "No changes to commit."
  if (-not $NoPush) {
    Write-Host "Pushing current branch HEAD to origin/main..."
    git push origin HEAD:main
    Assert-CommandSuccess "Git push"
  }
  exit 0
}

Write-Host "Committing: $CommitMessage"
git commit -m $CommitMessage
Assert-CommandSuccess "Git commit"

if ($NoPush) {
  Write-Host "Commit completed. Push skipped by -NoPush."
  exit 0
}

Write-Host "Pushing current branch HEAD to origin/main..."
git push origin HEAD:main
Assert-CommandSuccess "Git push"
Write-Host "Push completed. GitHub Actions will build and publish the latest release automatically."
