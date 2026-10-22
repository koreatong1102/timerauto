param([ValidateSet('ask','cpu','cu128')][string]$Runtime = 'ask')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv-qwen'
$python = Join-Path $venv 'Scripts\python.exe'
Write-Host 'Optional Qwen setup: separate Python environment; TimerAuto packages are not changed.'
Write-Host 'Downloads can be several GB. Close broadcasting workloads before testing GPU inference.'
if ($Runtime -eq 'ask') {
    Write-Host '1 = NVIDIA CUDA 12.8 build (compatible GPU/driver required); 2 = CPU (may be too slow for live calls)'
    $choice = Read-Host 'Choose 1 or 2; Enter cancels'
    if ($choice -eq '1') { $Runtime = 'cu128' }
    elseif ($choice -eq '2') { $Runtime = 'cpu' }
    else { Write-Host 'Cancelled. Nothing installed.'; exit 0 }
}
if (-not (Test-Path -LiteralPath $python)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Install Python 3.12 (64-bit) with the Python launcher from https://www.python.org/downloads/ first.'
    }
    & py -3.12 -c "import sys; assert sys.maxsize > 2**32; print(sys.version)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 64-bit is required. Other TimerAuto Python versions are left unchanged.' }
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Qwen environment.' }
}
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
& $python -m pip install --upgrade torch torchaudio --index-url "https://download.pytorch.org/whl/$Runtime"
if ($LASTEXITCODE -ne 0) { throw 'PyTorch install failed. Check network, GPU and Python version.' }
& $python -m pip install -r (Join-Path $root 'requirements-qwen.txt')
if ($LASTEXITCODE -ne 0) { throw 'Qwen dependency install failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Qwen dependency validation failed.' }
& $python -c "import torch, qwen_tts; print('CUDA available:', torch.cuda.is_available()); print('Torch:', torch.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Qwen import failed.' }
Write-Host 'Setup complete. Run the Qwen server launcher next. Model files download on that first run.'
