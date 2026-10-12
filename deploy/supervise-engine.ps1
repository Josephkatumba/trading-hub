param([Parameter(Mandatory=$true)][string]$ConfigPath,
      [int]$WarmupSeconds=600, [int]$FailureLimit=3)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'load-runtime.ps1') -ConfigPath $ConfigPath
$taskRepo = Split-Path $PSScriptRoot -Parent
if (-not $env:TRADEDEN_LOG_DIR) { throw 'Set protected TRADEDEN_LOG_DIR' }
New-Item -ItemType Directory -Force -Path $env:TRADEDEN_LOG_DIR | Out-Null
while ($true) {
    # Never stop or replace a listener that this supervisor did not start.
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { throw 'An engine already owns port 8000' }
    $taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $taskChild = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File', ('"' + (Join-Path $PSScriptRoot 'start-engine.ps1') + '"')) -RedirectStandardOutput (
        Join-Path $env:TRADEDEN_LOG_DIR "$taskStamp-out.log") -RedirectStandardError (
        Join-Path $env:TRADEDEN_LOG_DIR "$taskStamp-error.log")
    $taskStarted = Get-Date
    $taskFailures = 0
    while (-not $taskChild.HasExited) {
        Start-Sleep -Seconds 30
        if (((Get-Date) - $taskStarted).TotalSeconds -lt $WarmupSeconds) { continue }
        try {
            $taskReady = Invoke-RestMethod 'http://127.0.0.1:8000/api/ready' -TimeoutSec 10
            if (-not $taskReady.ready) { throw 'Not ready' }
            $taskFailures = 0
        } catch { $taskFailures++ }
        if ($taskFailures -ge $FailureLimit) {
            # Kill only this owned process tree; no global python/MT5 termination.
            & taskkill.exe /PID $taskChild.Id /T /F > $null 2>&1
            break
        }
        $taskChild.Refresh()
    }
    Start-Sleep -Seconds 30
}
