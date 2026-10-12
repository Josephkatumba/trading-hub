$ErrorActionPreference = 'Stop'
try {
    $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8000/api/ready' -TimeoutSec 10
    if (-not $taskHealth.ready) { throw 'Scanner is not ready' }
    Write-Output 'TRADEden scanner ready; execution disabled.'
    exit 0
} catch {
    Write-Error 'TRADEden scanner unhealthy. Inspect engine logs and MT5 connectivity.' -ErrorAction Continue
    exit 1
}
