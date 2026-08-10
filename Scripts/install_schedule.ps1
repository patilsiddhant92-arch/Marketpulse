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

# Do NOT use -StartWhenAvailable — that re-fires missed 8 PM runs the next morning
# (e.g. 9:30 AM popup). From now on: only at 20:00. If PC is off at 8 PM, skip that day.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
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
    -Description "MarketPulse EOD: only daily 20:00 local (no catch-up if missed). Pipeline may retry +10/+20 min within that run." | Out-Null

Write-Host "Registered scheduled task: $taskName"
Write-Host "  Script: $bat"
Write-Host "  Trigger: Daily at 20:00 local time ONLY"
Write-Host "  Catch-up: OFF (missed 8 PM will NOT run next morning)"
Write-Host "  In-run retries: pipeline may retry +10 min / +20 min if 8 PM attempt fails"
Write-Host "  Ensure Windows timezone is India Standard Time for 8 PM IST."

$tz = (Get-TimeZone).Id
Write-Host "  Current timezone: $tz"
if ($tz -notmatch "India") {
    Write-Host "  WARNING: timezone is not India. Adjust PC timezone or change the trigger if you need true IST."
}

Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Description
Get-ScheduledTaskInfo -TaskName $taskName | Format-List NextRunTime, LastRunTime, LastTaskResult
