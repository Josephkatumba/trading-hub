$ErrorActionPreference = 'Stop'
# The scanner reads NumPy rate arrays; it does not need parallel BLAS pools.
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$taskRepo = Split-Path $PSScriptRoot -Parent
if ($env:TRADING_HUB_AUTH_MODE -notin @('private', 'oidc')) {
    throw 'Select explicit private-owner or oidc-commercial authentication mode.'
}
if (-not $env:TRADING_HUB_DATA_DIR -or -not [System.IO.Path]::IsPathRooted($env:TRADING_HUB_DATA_DIR)) {
    throw 'Set TRADING_HUB_DATA_DIR to a persistent absolute path outside OneDrive.'
}
if (-not $env:TRADING_HUB_MT5_SOURCE_TIMEZONE) {
    throw 'Set the verified broker time basis before starting production.'
}
Set-Location (Join-Path $taskRepo 'backend')
if ($env:TRADING_HUB_PRIVATE_BETA -eq '1') {
    & (Join-Path $taskRepo '.venv/Scripts/python.exe') beta_preflight.py --online
    if ($LASTEXITCODE -ne 0) { throw 'Private beta preflight failed; engine not started' }
}
& (Join-Path $taskRepo '.venv/Scripts/python.exe') -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
exit $LASTEXITCODE
