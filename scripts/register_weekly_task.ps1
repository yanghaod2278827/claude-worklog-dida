# Register the weekly summary scheduled task (idempotent: -Force replaces it).
# Task lives in \个人自动化\ together with every other self-built task.
# ASCII only on purpose.
#
# Triggers (same philosophy as daily_worklog): a plain weekly trigger is silently
# skipped when the laptop is asleep (StartWhenAvailable only covers power-off),
# so use daily + logon + wake and let the script decide whether the week is due.

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'wl_config.ps1')
$schedCfg = Wl-ScheduleCfg
$TaskPath = Wl-Get $schedCfg 'task_folder' '\个人自动化\'
$TaskName = Wl-Get $schedCfg 'weekly_task' 'ClaudeCode-WeeklySummary'
$Script = Join-Path $PSScriptRoot 'weekly_summary.ps1'

if (-not (Test-Path $Script)) { throw "script not found: $Script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -File "{0}"' -f $Script)

# daily at 22:50 (after the 22:07 hourly archive, before the 23:07 one)
$tDaily = New-ScheduledTaskTrigger -Daily -At '22:50'

# at logon (catch-up after a missed Sunday)
$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# on resume from sleep (Kernel-Power 107)
$cls = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskEventTrigger'
$tWake = New-CimInstance -CimClass $cls -ClientOnly
$tWake.Enabled = $true
$tWake.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name="Microsoft-Windows-Kernel-Power"] and EventID=107]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
    -Action $action -Trigger @($tDaily, $tLogon, $tWake) `
    -Settings $settings -Principal $principal -Force `
    -Description 'Weekly: structured summary of the Mon-Sun week from Obsidian diary blocks -> 07-日记\<YYYY>-W<NN>_周总结.md' | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
Write-Host ("registered: {0}{1}  state={2}  triggers={3}" -f $t.TaskPath, $t.TaskName, $t.State, $t.Triggers.Count)
$i = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
Write-Host ("next run: {0}" -f $i.NextRunTime)
