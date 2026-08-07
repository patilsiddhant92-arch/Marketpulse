# Register daily MarketPulse EOD task at 20:00 local time (set PC timezone to IST).
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $root "Run_MarketPulse_Auto.bat"
$taskName = "MarketPulse_EOD"

if (-not (Test-Path $bat)) {
    throw "Missing launcher: $bat"
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$bat`"" `
    -WorkingDirectory $root

# Daily at 20:00 local. On an IST-configured PC this is 8 PM IST.
$trigger = New-ScheduledTaskTrigger -Daily -At "20:00"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

# Prefer current user so NSE download uses same network context; run whether logged on or not if password available.
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "MarketPulse EOD: download + append + Telegram at 20:00 local. On failure retries after 10 min (up to 3 attempts inside the pipeline)." | Out-Null

Write-Host "Registered scheduled task: $taskName"
Write-Host "  Script: $bat"
Write-Host "  Trigger: Daily at 20:00 local time"
Write-Host "  Retries: pipeline itself retries +10 min and +20 min if 8 PM fails"
Write-Host "  Ensure Windows timezone is India Standard Time for 8 PM IST."

$tz = (Get-TimeZone).Id
Write-Host "  Current timezone: $tz"
if ($tz -notmatch "India") {
    Write-Host "  WARNING: timezone is not India. Adjust PC timezone or change the trigger if you need true IST."
}

Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Description
Get-ScheduledTaskInfo -TaskName $taskName | Format-List NextRunTime, LastRunTime, LastTaskResult
