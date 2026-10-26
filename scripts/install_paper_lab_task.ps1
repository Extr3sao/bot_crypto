# Registers (or removes) the Windows 11 Scheduled Task that keeps the PAPER lab up.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_paper_lab_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_paper_lab_task.ps1 -Uninstall
#
# The task runs scripts\paper_lab_service.cmd, which starts the existing supervisor
# with a stable run id and --restart semantics. Nothing here holds credentials or
# reaches an exchange: the children are read-only market data and the PAPER broker.
#
# Restart policy is the point of using a task at all: the supervisor restarts its
# own children, and this restarts the supervisor if the host or the process dies.
param(
  [string]$RunId = "paper-lab-service",
  [string]$TaskName = "TradingAgenticPortablePaperLab",
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

if ($Uninstall) {
  $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($null -eq $existing) {
    Write-Host "[task] $TaskName is not registered; nothing to remove"
    exit 0
  }
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "[task] removed $TaskName"
  exit 0
}

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$wrapper = Join-Path $repo "scripts\paper_lab_service.cmd"
if (-not (Test-Path $wrapper)) {
  throw "service wrapper not found: $wrapper"
}

$action = New-ScheduledTaskAction `
  -Execute "cmd.exe" `
  -Argument "/c `"$wrapper`" $RunId" `
  -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
  -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive `
  -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Trading Agentic Portable - PAPER/SHADOW lab with real market data, read-only AI commentary. No live trading." `
  -Force | Out-Null

Write-Host "[task] registered $TaskName"
Write-Host "[task] command : cmd.exe /c `"$wrapper`" $RunId"
Write-Host "[task] run id  : $RunId"
Write-Host "[task] verify  : uv run python scripts/paper_lab_status.py"
Write-Host "[task] console : scripts\paper_lab_dashboard.cmd  (http://127.0.0.1:8787)"
