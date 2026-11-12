# Register the daily worklog scheduled task (idempotent: -Force replaces it).
# ASCII only.
#
# Task lives in \个人自动化\ since the 2026-11-05 migration. Registering it at the
# root again would create a SECOND copy, so keep -TaskPath here.

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'wl_config.ps1')
$schedCfg = Wl-ScheduleCfg
$TaskPath = Wl-Get $schedCfg 'task_folder' '\个人自动化\'
$TaskName = Wl-Get $schedCfg 'worklog_task' 'ClaudeCode-DailyWorkLog'
$Script = Join-Path $PSScriptRoot 'daily_worklog.ps1'

if (-not (Test-Path $Script)) { throw "script not found: $Script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -File "{0}"' -f $Script)

# trigger 1: daily at 00:07, repeated hourly for 24h, so late-night work still gets
# synced. The script itself no-ops when nothing new happened.
$tDaily = New-ScheduledTaskTrigger -Daily -At '00:07'
$repSrc = New-ScheduledTaskTrigger -Once -At '00:07' `
    -RepetitionInterval (New-TimeSpan -Minutes 60) `
    -RepetitionDuration (New-TimeSpan -Hours 24)
$tDaily.Repetition = $repSrc.Repetition

# trigger 2: at logon
$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# trigger 3: on resume from sleep (Kernel-Power 107)
$cls = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskEventTrigger'
$tWake = New-CimInstance -CimClass $cls -ClientOnly
$tWake.Enabled = $true
$tWake.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name="Microsoft-Windows-Kernel-Power"] and EventID=107]]</Select></Query></QueryList>'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
    -Action $action -Trigger @($tDaily, $tLogon, $tWake) `
    -Settings $settings -Principal $principal -Force `
    -Description 'Daily: extract local Claude sessions and record work into Dida365 as completed tasks' | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
Write-Host ("registered: {0}{1}  state={2}  triggers={3}" -f $t.TaskPath, $t.TaskName, $t.State, $t.Triggers.Count)
$i = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
Write-Host ("next run: {0}" -f $i.NextRunTime)
