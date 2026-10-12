param([Parameter(Mandatory=$true)][string]$ConfigPath,
      [Parameter(Mandatory=$true)][string]$BackupDirectory)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'load-runtime.ps1') -ConfigPath $ConfigPath
# Use PGHOST/PGPORT/PGUSER/PGDATABASE and protected PGPASSFILE. No passwords in argv.
if (-not $env:PGPASSFILE -or -not (Test-Path -LiteralPath $env:PGPASSFILE)) { throw 'Protected PGPASSFILE required' }
foreach ($taskName in @('PGHOST','PGUSER','PGDATABASE')) {
    if (-not [Environment]::GetEnvironmentVariable($taskName)) { throw 'PostgreSQL backup connection is incomplete' }
}
New-Item -ItemType Directory -Force -Path $BackupDirectory | Out-Null
$taskBackup = Join-Path $BackupDirectory ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.dump')
& pg_dump --format=custom --no-password --file=$taskBackup
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed; preserve failed output for administrator review' }
& pg_restore --list $taskBackup > $null
if ($LASTEXITCODE -ne 0) { throw 'Database archive verification failed' }
Get-FileHash -LiteralPath $taskBackup -Algorithm SHA256 | Select-Object -ExpandProperty Hash | Set-Content ($taskBackup + '.sha256')
Write-Output 'PostgreSQL archive and checksum created. A restore into a separate database is still required.'
