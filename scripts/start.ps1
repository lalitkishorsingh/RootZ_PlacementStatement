$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $taskPython -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $taskPython scripts/setup_local.py
& $taskPython manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' }
Write-Host 'Open http://127.0.0.1:8000. To seed synthetic data, run manage.py seed_demo separately on an empty database.'
& $taskPython manage.py runserver 127.0.0.1:8000 --noreload
