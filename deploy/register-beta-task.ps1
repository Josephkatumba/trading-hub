param([Parameter(Mandatory=$true)][string]$ConfigPath,
      [Parameter(Mandatory=$true)][string]$RuntimeUser, [switch]$Install)
$ErrorActionPreference = 'Stop'
$taskScript = Join-Path $PSScriptRoot 'supervise-engine.ps1'
if (-not $Install) { Write-Output 'Prepared: at-logon scanner supervisor, same MT5 user, no overlap, restart after failure. Pass -Install only on the designated VPS.'; exit 0 }
$taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    '-NoProfile -ExecutionPolicy RemoteSigned -File "' + $taskScript + '" -ConfigPath "' + $ConfigPath + '"')
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $RuntimeUser
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $RuntimeUser -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (
    New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'TRADEden Private Beta Scanner' -Action $taskAction -Trigger $taskTrigger -Principal (
    $taskPrincipal) -Settings $taskSettings | Out-Null
