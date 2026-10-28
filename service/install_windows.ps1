<#
.SYNOPSIS
  Registers SortSmart as a scheduled task that starts at logon and restarts on failure.
.EXAMPLE
  .\service\install_windows.ps1 -Config C:\SortSmart\rules.yaml
#>
param(
    [Parameter(Mandatory = $true)][string]$Config,
    [string]$TaskName = "SortSmart"
)
$ErrorActionPreference = "Stop"

$Config = (Resolve-Path $Config).Path
$exe = (Get-Command sortsmart -ErrorAction SilentlyContinue).Source
if (-not $exe) { throw "sortsmart is not on PATH; run: pip install sortsmart" }

$action = New-ScheduledTaskAction -Execute $exe -Argument "watch --config `"$Config`"" `
    -WorkingDirectory (Split-Path $Config)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "SortSmart file intake watcher" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered and started scheduled task '$TaskName' (config: $Config)."
Write-Host "Remove with: .\service\uninstall_windows.ps1"
