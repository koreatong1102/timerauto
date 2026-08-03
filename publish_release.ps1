param(
  [string]$CommitMessage = "chore: publish TimerAuto update",
  [switch]$SkipChecks,
  [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$env:GIT_PAGER = "cat"
$env:GIT_TERMINAL_PROMPT = "0"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Assert-CommandSuccess([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE."
  }
}

function Push-ToMain {
  Write-Host "Syncing with origin/main..."
  git fetch origin main
  Assert-CommandSuccess "Git fetch"
  git rebase origin/main
  Assert-CommandSuccess "Git rebase"
  Write-Host "Pushing current branch HEAD to origin/main..."
  git push origin HEAD:main
  Assert-CommandSuccess "Git push"
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
  # Git for Windows can emit one CRLF warning per modified file and has been
  # observed to remain attached to the legacy console afterwards.  Disable
  # safe-CRLF warnings for this read-only whitespace check and bypass all
  # external diff/pager hooks so publishing cannot stall here.
  git -c core.safecrlf=false --no-pager diff --check --no-ext-diff 2>$null
  Assert-CommandSuccess "Git diff check"
}

Write-Host "Staging tracked and new project files..."
git -c core.safecrlf=false add -A
Assert-CommandSuccess "Git staging"

$staged = git diff --cached --name-only
if (-not $staged) {
  Write-Host "No changes to commit."
  if (-not $NoPush) {
    Push-ToMain
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

Push-ToMain
Write-Host "Push completed. GitHub Actions will build and publish the latest release automatically."
