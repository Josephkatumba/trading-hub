param([Parameter(Mandatory=$true)][string]$ConfigPath)
$ErrorActionPreference = 'Stop'
# Protected JSON is loaded as DATA, never evaluated as script; never print its values.
try { $taskConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json }
catch { throw 'Protected runtime JSON is missing or invalid; values are withheld' }
foreach ($taskProperty in $taskConfig.PSObject.Properties) {
    if ($taskProperty.Name -notmatch '^(TRADING_HUB_|TRADEDEN_|PG)[A-Z0-9_]+$') { throw 'Unexpected runtime configuration key' }
    [Environment]::SetEnvironmentVariable($taskProperty.Name, [string]$taskProperty.Value, 'Process')
}
