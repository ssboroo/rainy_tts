param([switch]$InstallModel)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
function Invoke-Checked {
    param([string]$Exe, [string[]]$CommandArgs)
    & $Exe @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Exe" }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw 'FFmpeg is required. Install FFmpeg, reopen PowerShell, and run this script again.'
}
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Invoke-Checked -Exe 'py' -CommandArgs @('-3.12','-m','venv','.venv')
}
$env:PUBLIC_ORIGIN = 'http://localhost:8080'
$env:HOST = '127.0.0.1'
$env:PORT = '8080'
$env:ALLOW_REGISTRATION = 'true'
$env:TTS_USAGE_MODE = 'local-evaluation'
$env:MODEL_LICENSE_APPROVED = 'false'
$env:MODEL_DIR = Join-Path $root 'models\oron'
$env:DATA_DIR = Join-Path $root 'data'
$env:OMP_NUM_THREADS = '4'
if ($InstallModel) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required for model installation.' }
    Invoke-Checked -Exe $python -CommandArgs @('-m','pip','install','torch==2.8.0','torchaudio==2.8.0','--index-url','https://download.pytorch.org/whl/cpu')
    Invoke-Checked -Exe $python -CommandArgs @('-m','pip','install','-c','requirements-model.constraints.txt','f5-tts @ git+https://github.com/SWivid/F5-TTS.git@283252563dbf91be625e0c27926acfaac449186c','oron-tts @ git+https://github.com/btseee/oron-tts.git@494c3940518cf2246fec5833b45da1a78acd7f03')
    Invoke-Checked -Exe $python -CommandArgs @('scripts/download_model.py')
}
Invoke-Checked -Exe $python -CommandArgs @('-c','from app.engine import OronEngine; import sys; ok, message = OronEngine().readiness(); print(message); sys.exit(0 if ok else 1)')
$worker = Start-Process -FilePath $python -ArgumentList @('-m','app.worker') -WorkingDirectory $root -PassThru -NoNewWindow
try {
    Write-Host 'Open http://localhost:8080. Local evaluation only; CPU generation can take several minutes.'
    Invoke-Checked -Exe $python -CommandArgs @('-m','app.server')
} finally {
    if (-not $worker.HasExited) { Stop-Process -Id $worker.Id }
}
