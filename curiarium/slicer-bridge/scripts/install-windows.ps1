param(
  [string]$BridgePath = ""
)

$ErrorActionPreference = "Stop"

if (-not $BridgePath) {
  $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $BridgePath = Join-Path $scriptDir "..\dist\slicer-bridge.exe"
}

$BridgePath = (Resolve-Path $BridgePath).Path
$targetDir = Join-Path $env:LOCALAPPDATA "Curiarium\SlicerBridge"
$targetExe = Join-Path $targetDir "curiarium-slicer.exe"

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -Path $BridgePath -Destination $targetExe -Force

function Register-Protocol {
  param(
    [string]$Protocol,
    [string]$Label,
    [string]$TargetExe
  )
  $root = "HKCU:\Software\Classes\$Protocol"
  New-Item -Path $root -Force | Out-Null
  New-ItemProperty -Path $root -Name "(Default)" -Value "URL:$Label" -PropertyType String -Force | Out-Null
  New-ItemProperty -Path $root -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null
  $commandKey = "$root\shell\open\command"
  New-Item -Path $commandKey -Force | Out-Null
  Set-ItemProperty -Path $commandKey -Name "(Default)" -Value "`"$TargetExe`" `"%1`"" -Force
}

Register-Protocol -Protocol "curiarium-slicer" -Label "Curiarium Slicer Bridge" -TargetExe $targetExe
Register-Protocol -Protocol "curiarium-engrave" -Label "Curiarium Engraving Bridge" -TargetExe $targetExe

Write-Host "Installed protocol handler at $targetExe"
