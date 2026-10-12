param([int]$Seconds = 120, [string]$OutputPath = 'runtime-measurements.json')
$ErrorActionPreference = 'Stop'
$taskPort = Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -First 1
$taskEngineId = $taskPort.OwningProcess
$taskIds = @($taskEngineId) + @(Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$taskSamples = @()
$taskClock = [Diagnostics.Stopwatch]::StartNew()
while ($taskClock.Elapsed.TotalSeconds -lt $Seconds) {
    foreach ($taskProcessId in $taskIds) {
        $taskProcess = Get-Process -Id $taskProcessId -ErrorAction SilentlyContinue
        if ($taskProcess) {
            $taskSamples += [pscustomobject]@{
                seconds = $taskClock.Elapsed.TotalSeconds
                id = $taskProcess.Id
                name = $taskProcess.ProcessName
                cpu_seconds = $taskProcess.CPU
                working_mb = $taskProcess.WorkingSet64 / 1MB
                private_mb = $taskProcess.PrivateMemorySize64 / 1MB
            }
        }
    }
    Start-Sleep -Seconds 2
}
$taskSummary = @()
foreach ($taskProcessId in $taskIds) {
    $taskRows = @($taskSamples | Where-Object id -eq $taskProcessId)
    if ($taskRows.Count -gt 1) {
        $taskFirst = $taskRows[0]; $taskLast = $taskRows[-1]
        $taskSummary += [pscustomobject]@{
            name = $taskFirst.name
            id = $taskProcessId
            observed_seconds = $taskLast.seconds - $taskFirst.seconds
            cpu_percent_one_core = 100 * ($taskLast.cpu_seconds - $taskFirst.cpu_seconds) / ($taskLast.seconds - $taskFirst.seconds)
            max_private_mb = ($taskRows | Measure-Object private_mb -Maximum).Maximum
            max_working_mb = ($taskRows | Measure-Object working_mb -Maximum).Maximum
        }
    }
}
[pscustomobject]@{ captured_at = [DateTime]::UtcNow.ToString('o'); samples = $taskSamples; summary = $taskSummary } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding utf8
$taskSummary | ConvertTo-Json
