param([Parameter(Mandatory=$true)][string]$JobFile,
      [Parameter(Mandatory=$true)][string]$ProgressFile,
      [Parameter(Mandatory=$true)][string]$CancelFile)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv-qwen\Scripts\python.exe'
$env:HF_HOME = Join-Path $root '.qwen_models'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
function Test-Cancelled {
    if (Test-Path -LiteralPath $CancelFile) { throw 'Voice pack creation cancelled.' }
}
try {
    Test-Cancelled
    $runtimeReady = $false
    if (Test-Path -LiteralPath $python) {
        & $python -c "import torch, qwen_tts, soundfile, numpy; print('Qwen runtime ready')"
        $runtimeReady = ($LASTEXITCODE -eq 0)
    }
    if (-not $runtimeReady) {
        Write-Output 'Preparing an isolated Qwen environment. Existing TimerAuto packages are not changed.'
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            throw 'Python launcher is missing. Install Python 3.12 64-bit from python.org, then click the one-click button again.'
        }
        & py -3.12 -c "import sys; assert sys.maxsize > 2**32"
        if ($LASTEXITCODE -ne 0) {
            # Python Install Manager supports this command; old launchers fail
            # safely without changing the existing TimerAuto environment.
            & py install 3.12
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 could not be installed. Install Python 3.12 64-bit, then retry.' }
        }
        Test-Cancelled
        $runtime = 'cpu'
        if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
            & nvidia-smi --query-gpu=name --format=csv,noheader
            if ($LASTEXITCODE -eq 0) { $runtime = 'cu128' }
        }
        & (Join-Path $root 'setup_qwen.ps1') -Runtime $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Qwen environment installation failed. See setup.log.' }
    }
    Test-Cancelled
    & $python -u (Join-Path $root 'qwen_duo_builder.py') --job $JobFile --progress $ProgressFile --cancel $CancelFile
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    $status = if (Test-Path -LiteralPath $CancelFile) { 'cancelled' } else { 'error' }
    $message = if ($status -eq 'cancelled') { 'Creation cancelled. Completed clips are kept for resume.' } else { 'Setup failed: ' + $_.Exception.Message }
    $record = @{status=$status;message=$message} | ConvertTo-Json -Compress
    [IO.File]::AppendAllText($ProgressFile, $record + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    exit 1
}
