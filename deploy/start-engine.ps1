$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path $PSScriptRoot -Parent
if (-not $env:TRADING_HUB_DATA_DIR -or -not [System.IO.Path]::IsPathRooted($env:TRADING_HUB_DATA_DIR)) {
    throw 'Set TRADING_HUB_DATA_DIR to a persistent absolute path outside OneDrive.'
}
if (-not $env:TRADING_HUB_MT5_SOURCE_TIMEZONE) {
    throw 'Set the verified broker time basis before starting production.'
}
Set-Location (Join-Path $taskRepo 'backend')
& (Join-Path $taskRepo '.venv/Scripts/python.exe') -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
exit $LASTEXITCODE
