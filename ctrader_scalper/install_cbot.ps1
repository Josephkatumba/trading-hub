# Installs (or updates) the TradeDen Scalper cBot source into cTrader's Algo folder.
#   powershell -ExecutionPolicy Bypass -File ctrader_scalper\install_cbot.ps1            # install / update
#   powershell -ExecutionPolicy Bypass -File ctrader_scalper\install_cbot.ps1 -DryRun    # show what would happen
# It only copies source files. It never starts the cBot, never touches accounts or settings.
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'

$src = Join-Path $PSScriptRoot 'cbot\TradeDenScalper.cs'
$docs = [Environment]::GetFolderPath('MyDocuments')
$robots = Join-Path $docs 'cAlgo\Sources\Robots'
if (-not (Test-Path $robots)) { throw "cTrader Algo folder not found at $robots. Open cTrader once (Algo tab) and retry." }

$root = Join-Path $robots 'TradeDenScalper'
$proj = Join-Path $root 'TradeDenScalper'
$csTarget = Join-Path $proj 'TradeDenScalper.cs'
$csproj = Join-Path $proj 'TradeDenScalper.csproj'
$sln = Join-Path $root 'TradeDenScalper.sln'

Write-Host "Source : $src"
Write-Host "Target : $csTarget"
if ($DryRun) {
  Write-Host "[dry run] would create $proj (exists: $(Test-Path $proj))"
  Write-Host "[dry run] would $(if (Test-Path $csTarget) {'back up and replace'} else {'create'}) TradeDenScalper.cs"
  Write-Host "[dry run] would create csproj/sln only if missing (exists: $(Test-Path $csproj) / $(Test-Path $sln))"
  exit 0
}

New-Item -ItemType Directory -Force $proj | Out-Null
if (Test-Path $csTarget) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  Copy-Item $csTarget "$csTarget.$stamp.bak"
  Write-Host "Backed up previous source to TradeDenScalper.cs.$stamp.bak"
}
Copy-Item $src $csTarget -Force

if (-not (Test-Path $csproj)) {
@'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="cTrader.Automate" Version="*" />
  </ItemGroup>
</Project>
'@ | Set-Content -Encoding utf8 $csproj
}
if (-not (Test-Path $sln)) {
  $guid = [guid]::NewGuid().ToString().ToUpper()
@"
Microsoft Visual Studio Solution File, Format Version 12.00
Project("{9A19103F-16F7-4668-BE54-9A1E7A4F7556}") = "TradeDenScalper", "TradeDenScalper\TradeDenScalper.csproj", "{$guid}"
EndProject
"@ | Set-Content -Encoding utf8 $sln
}
Write-Host ""
Write-Host "Installed. In cTrader: Algo tab -> cBots -> TradeDenScalper -> Build (Ctrl+B)."
Write-Host "If it does not appear, restart cTrader, or create a new cBot named TradeDenScalper and paste the file content."
