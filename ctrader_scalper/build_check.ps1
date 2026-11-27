# Offline compile check of the cBot against cTrader's own cAlgo.API.dll (no .NET SDK needed).
$ErrorActionPreference = 'Stop'
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$api = if ($env:CALGO_API_DLL) { $env:CALGO_API_DLL } else {
  Get-ChildItem "$env:LOCALAPPDATA\Spotware\cTrader\*\app_*\algohost.netframework\cAlgo.API.dll" | Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName
}
if (-not $api) { throw 'cAlgo.API.dll not found; install cTrader or set CALGO_API_DLL.' }
$out = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force $out | Out-Null
foreach ($bot in 'TradeDenScalper', 'TradeDenCollector') {
  & $csc -nologo -target:library -warn:4 -nowarn:1685 "-r:$api" "-out:$out\$bot.dll" (Join-Path $PSScriptRoot "cbot\$bot.cs")
  if ($LASTEXITCODE -ne 0) { throw "$bot compile failed ($LASTEXITCODE)" }
  Write-Host "OK: $bot compiles against $api"
}
