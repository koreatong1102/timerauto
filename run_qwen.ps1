param([ValidateSet('auto','cpu','cuda:0')][string]$Device = 'auto')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv-qwen\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run the Qwen setup launcher first (Python 3.12 required).' }
$model = '1.7B'
$portNumber = 8768
$config = Join-Path $root 'config.json'
if (Test-Path -LiteralPath $config) {
    $data = [IO.File]::ReadAllText($config, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($data.spectator_qwen_model -in @('0.6B','1.7B')) { $model = $data.spectator_qwen_model }
    if ($data.spectator_qwen_port -and [int]$data.spectator_qwen_port -ge 1024 -and [int]$data.spectator_qwen_port -le 65535) {
        $portNumber = [int]$data.spectator_qwen_port
    }
}
$env:HF_HOME = Join-Path $root '.qwen_models'
$env:PYTHONUTF8 = '1'
Write-Host "Qwen $model on local port $portNumber. Wait for READY before testing. Ctrl+C stops this optional server."
Write-Host 'The first start downloads model files. Do not close this window while Qwen is in use.'
& $python -u (Join-Path $root 'qwen_tts_server.py') --model $model --port $portNumber --device $Device
if ($LASTEXITCODE -ne 0) { throw 'Qwen server stopped with an error. Read the server output above.' }
