# Print scheduled task runtime facts. ASCII output only.
# Get-ScheduledTaskInfo NEEDS -TaskPath: after the 2026-11-05 move into \个人自动化\
# a bare -TaskName throws (observed 2026-11-06) and the whole audit dies silently.
param([string]$TaskName = '', [string]$TaskPath = '')

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'wl_config.ps1')
$schedCfg = Wl-ScheduleCfg
if (-not $TaskName) { $TaskName = Wl-Get $schedCfg 'worklog_task' 'ClaudeCode-DailyWorkLog' }
if (-not $TaskPath) { $TaskPath = Wl-Get $schedCfg 'task_folder' '\个人自动化\' }

$t = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
$i = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath

Write-Output "TASK=$($t.TaskPath)$($t.TaskName)"
Write-Output "STATE=$($t.State)"
Write-Output "LAST_RUN=$($i.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Output "LAST_RESULT=$($i.LastTaskResult)"
Write-Output "NEXT_RUN=$($i.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Output "MISSED=$($i.NumberOfMissedRuns)"
Write-Output "NOW=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output '--- triggers ---'
$k = 0
foreach ($tr in $t.Triggers) {
    $k++
    $st = ''
    if ($tr.StartBoundary) { $st = $tr.StartBoundary }
    $rep = ''
    if ($tr.Repetition -and $tr.Repetition.Interval) {
        $rep = "interval=$($tr.Repetition.Interval) duration=$($tr.Repetition.Duration)"
    }
    Write-Output ("T{0} {1} start={2} {3}" -f $k, $tr.CimClass.CimClassName, $st, $rep)
}
Write-Output '--- settings ---'
Write-Output "DisallowStartIfOnBatteries=$($t.Settings.DisallowStartIfOnBatteries)"
Write-Output "StopIfGoingOnBatteries=$($t.Settings.StopIfGoingOnBatteries)"
Write-Output "StartWhenAvailable=$($t.Settings.StartWhenAvailable)"
