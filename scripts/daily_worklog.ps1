# Daily: extract today's local Claude sessions -> record work into Dida365 as completed tasks.
# ASCII only on purpose (non-ASCII comments can swallow newlines on this machine).
param([string]$Date = '', [switch]$Force, [switch]$DryRun)  # backfill: -Date yyyy-MM-dd [-Force]

$ErrorActionPreference = 'Continue'
# decode child-process stdout (python/claude emit UTF-8, not GBK)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'wl_config.ps1')
. (Join-Path $PSScriptRoot 'wl_config.ps1')
$HomeDir = $env:USERPROFILE
$Project = $WlRoot
$Scripts = Join-Path $Project 'scripts'
$Logs = Join-Path $Project 'logs'
$Data = Join-Path $Project 'data'
$Log = Join-Path $Logs 'daily_worklog.log'
$StateFile = Join-Path $Data 'worklog_state.json'
$Vault = Wl-Vault
$schedCfg = Wl-ScheduleCfg
$TaskFolder = Wl-Get $schedCfg 'task_folder' '\个人自动化\'
$TaskName = Wl-Get $schedCfg 'worklog_task' 'ClaudeCode-DailyWorkLog'
$claudeCfg = Wl-ClaudeCfg
$ClaudeCmd = Wl-Get $claudeCfg 'command' 'claude'
$CostScript = Wl-Expand (Wl-Get $claudeCfg 'cost_script' '')
$TzOffset = Wl-TzOffset
# whole-machine filesystem evidence scanner (2026-10-30)
$FsScript = Join-Path $Scripts 'fs_evidence.py'
$FsState = Join-Path $Data 'fs_scope.json'

foreach ($d in @($Logs, $Data)) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }

function Write-Log([string]$msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

$Py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }

# NOTE: PS variables are case-insensitive, so $date below IS the -Date parameter.
# Capture the backfill flag BEFORE it gets overwritten with today's date.
$isBackfill = [bool]$Date
if ($Date) { $date = $Date } else { $date = Get-Date -Format 'yyyy-MM-dd' }
$now = Get-Date

# ---- throttle: re-run whenever new local activity appeared (no daily run cap) ----
# state: { lastRun: ISO8601, today: yyyy-MM-dd, count: n }
$lastRun = $null
$count = 0
if (Test-Path $StateFile) {
    try {
        $st = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($st.lastRun) { $lastRun = [datetime]::Parse($st.lastRun) }
        if ($st.today -eq $date) { $count = [int]$st.count }
    } catch { }
}

# ---- self-heal (2026-11-04): the hourly slot can be skipped entirely (observed: 10:07 run had
# no task-scheduler event at all while NumberOfMissedRuns went to 1). When the script does get
# launched later (wake / logon / next slot) and the last SUCCESSFUL run is older than 120 min,
# force past the activity throttle so the missed window is archived now. If no evidence exists the
# script still exits before calling the model, so this cannot waste money.
$selfHealMin = 120
$staleMin = ''
$missedRuns = ''
if (-not $isBackfill -and -not $Force) {
    $lastOk = $null
    if (Test-Path $Log) {
        foreach ($ln in (Get-Content $Log -Tail 500 -Encoding UTF8)) {
            if ($ln -match '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] DONE ') {
                $lastOk = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null)
            }
        }
    }
    if ($lastOk) {
        $staleMin = [int]((Get-Date) - $lastOk).TotalMinutes
        if ($staleMin -gt $selfHealMin) { $Force = $true }
    }
    # NOTE: after the 2026-11-05 move into \个人自动化\, Get-ScheduledTaskInfo needs -TaskPath.
    # Without it the call throws and $missedRuns stays blank (silent, observed 2026-11-06).
    try { $missedRuns = (Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskFolder -ErrorAction Stop).NumberOfMissedRuns } catch { }
    Write-Log ("SELFHEAL stale_min={0} missed={1} force={2}" -f $staleMin, $missedRuns, [bool]$Force)
}

$sessIdle = $false
if ($lastRun -and -not $Force) {
    # newest transcript mtime across all projects; do NOT exit here - file changes may still exist
    $newest = Get-ChildItem -Path (Join-Path $HomeDir '.claude\projects') -Filter '*.jsonl' -Recurse -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest -and $newest.LastWriteTime -le $lastRun.AddMinutes(2)) { $sessIdle = $true }
}

Set-Location $HomeDir

# ---- 1. extract session evidence ----
$evidence = Join-Path $Data ('worklog_evidence_{0}.txt' -f $date)
Remove-Item $evidence -Force -ErrorAction SilentlyContinue
$evOut = & $Py (Join-Path $Scripts 'worklog_extract.py') --date $date --out $evidence 2>&1 | Out-String
$code = $LASTEXITCODE
Write-Log ("EXTRACT rc={0} :: {1}" -f $code, $evOut.Trim())
if ($code -eq 1) { Write-Log "FAIL extract"; exit 1 }
# rc=2 (no sessions today) is no longer fatal: whole-machine file changes may still be work.

# ---- 1b. filesystem change evidence (whole machine, appended to same evidence file) ----
$fsArgs = @('--date', $date, '--append-to', $evidence, '--state', $FsState)
# backfill mode (-Date) must not pollute the adaptive hot-dir learning state
if ($Date) { $fsArgs += '--no-state' }
$fsOut = & $Py $FsScript @fsArgs 2>&1 | Out-String
$fsCode = $LASTEXITCODE
Write-Log ("FSEV rc={0} :: {1}" -f $fsCode, $fsOut.Trim())
if ($fsCode -eq 1) { Write-Log "WARN fs evidence failed; continuing with session evidence only" }
$fsSig = ''
if ($fsOut -match 'sig=([0-9a-zA-Z]+)') { $fsSig = $Matches[1] }
$FsSigFile = Join-Path $Data ('fs_sig_{0}.txt' -f $date)
$oldSig = ''
if (Test-Path $FsSigFile) { $oldSig = (Get-Content -Path $FsSigFile -Raw -Encoding UTF8).Trim() }
if ($fsSig) { Set-Content -Path $FsSigFile -Value $fsSig -Encoding UTF8 }

if (-not (Test-Path $evidence)) { Write-Log ("SKIP {0} no evidence (no sessions, no file changes)" -f $date); exit 0 }
if ((-not $Force) -and $sessIdle -and $fsSig -and $oldSig -and ($fsSig -eq $oldSig)) {
    Write-Log ("SKIP no new activity (newest session <= lastRun+2m, fs sig unchanged {0})" -f $fsSig)
    exit 0
}
if ($DryRun) {
    $evLen = (Get-Item $evidence).Length
    Write-Log ("DRYRUN evidence={0} bytes session_rc={1} fs_rc={2} fs_sig={3}" -f $evLen, $code, $fsCode, $fsSig)
    exit 0
}

$Lang = Wl-Get $WlCfg 'prompt_lang' 'zh'
$PromptSrc = Join-Path $Scripts ('worklog_prompt.{0}.md' -f $Lang)
$promptFile = Join-Path $Data ('worklog_prompt_rendered_{0}.md' -f $date)
$renderOut = & $Py (Join-Path $Scripts 'render_prompt.py') --template $PromptSrc --out $promptFile 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Write-Log ('FAIL render prompt :: ' + $renderOut.Trim()); exit 1 }
if (-not (Test-Path $evidence)) { Write-Log "FAIL evidence missing"; exit 1 }

# ---- 2. call claude -p ----
$McpPrefix = 'mcp__' + (Wl-Get $WlCfg 'task_manager' 'dida365') + '__'
$claude = $ClaudeCmd
if (-not (Test-Path $claude)) { $claude = Join-Path $env:APPDATA 'npm\claude.cmd' }
if (-not (Test-Path $claude)) { $claude = 'claude' }

# completion timestamp must be in the PAST, otherwise TickTick hides the task:
# a future completedTime never shows up in the 已完成 list (observed 2026-10-29).
$nowTs = Get-Date
# 当天：上限一律用「此刻」（永远在过去，且能覆盖 21:00 之后的晚间工作——2026-11-06 改；
# 原写法 Hour -ge 21 就退化成 T21:00，配合步骤 3.5 的延时会把晚间工作全压平成 21:00）。
# 回填历史日期：那天早已结束，用 21:00 作为保守上限。
if ($date -eq $nowTs.ToString('yyyy-MM-dd')) {
    $ctStamp = ('{0}T{1}{2}' -f $date, $nowTs.ToString('HH:mm:00'), $TzOffset)
} else {
    $ctStamp = ('{0}T21:00:00{1}' -f $date, $TzOffset)
}
$diary = Join-Path $Vault ('{0}.md' -f $date)
# last-update stamp for task content + the diary block (always the real current moment)
$updatedAt = (Get-Date -Format 'yyyy-MM-dd HH:mm')
$runNumber = $count + 1
Write-Log ("CTSTAMP=$ctStamp UPDATED_AT=$updatedAt RUN=$runNumber")
$instr = ('Read the instruction file {0} and follow it strictly. Evidence file: {1}. Date: {2}. Diary file: {3}. Fallback time and upper bound for each task end time, never exceed it: {4}. Last-update timestamp to write into task content and the diary block: {5}. This is run number {6} for this date. Step 6 (sync to Obsidian diary) is mandatory. Print only the final result line.' -f $promptFile, $evidence, $date, $diary, $ctStamp, $updatedAt, $runNumber)

$tmpOut = Join-Path $env:TEMP 'worklog_stdout.txt'
$tmpErr = Join-Path $env:TEMP 'worklog_stderr.txt'

# Cost accounting: DeepSeek bills in RMB, so the RMB figure comes from cc_cny_peak.py
# (accurate: dedupe by message.id + peak/off-peak pricing). --max-budget-usd is NOT used:
# it is USD-denominated and this model id is unknown to claude-code's price table
# ("unrecognized_model"), so it is neither applicable nor trustworthy here.
# CostScript defined at top

function Get-TodayCny([string]$d) {
    if (-not $CostScript -or -not (Test-Path $CostScript)) { return -1 }
    try {
        $raw = (& $Py $CostScript --date $d --json) | Out-String
        $o = $raw.Trim() | ConvertFrom-Json
        return [double]$o.total
    } catch { return -1 }
}

# cost is billed TODAY even when backfilling an old date, so always meter today's total
$costDate = if ($Date) { (Get-Date -Format 'yyyy-MM-dd') } else { $date }
$preCny = Get-TodayCny $costDate

# Start-Process does not quote array items, so build one quoted argument string.
$argStr = @(
    '-p', ('"{0}"' -f $instr),
    '--permission-mode', 'auto',
    '--allowedTools', ('Read,Write,Bash,Glob,Grep,' + $McpPrefix + 'list_completed_tasks_by_date,' + $McpPrefix + 'batch_add_tasks,' + $McpPrefix + 'batch_update_tasks')
) -join ' '

$proc = Start-Process -FilePath $claude -ArgumentList $argStr -NoNewWindow -PassThru `
    -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
$timeoutMs = 600000
if (-not $proc.WaitForExit($timeoutMs)) {
    try { $proc.Kill() } catch { }
    Write-Log "FAIL claude timeout after $timeoutMs ms"
    exit 1
}
# ExitCode from Start-Process + redirected streams is often empty; judge by output instead.
$rc = $proc.ExitCode
$out = ''
if (Test-Path $tmpOut) { $out = (Get-Content $tmpOut -Raw -Encoding UTF8) }
$tail = $out.Trim()
$ok = ($tail -match 'DONE date=') -or ($tail -match 'NO_WORK')

# verify the diary block actually landed
$diaryOk = $false
if (Test-Path $diary) {
    $did = Get-Content $diary -Raw -Encoding UTF8
    $diaryOk = ($did -match 'dida365:begin') -and ($did -match 'dida365:end')
}
if ($tail -match 'NO_WORK') { $diaryOk = $true }
if (-not $diaryOk) { $ok = $false }

if ($tail.Length -gt 1200) { $tail = $tail.Substring($tail.Length - 1200) }
$tail = ('diary={0} :: {1}' -f $diaryOk, $tail)

$postCny = Get-TodayCny $costDate
if ($preCny -ge 0 -and $postCny -ge 0) {
    $runCny = $postCny - $preCny
    $costMsg = ('cost=CNY {0:N3} (day total CNY {1:N2})' -f $runCny, $postCny)
} else {
    $costMsg = 'cost=CNY n/a'
}
Write-Log ("CLAUDE rc={0} ok={1} {2} :: {3}" -f $rc, $ok, $costMsg, $tail)

# ---- duplicate self-check result (reported by the agent, never deleted automatically) ----
$dupLines = @($out -split "`r?`n" | Where-Object { $_ -match '^DUP:' })
if ($dupLines.Count -gt 0) {
    $dupFile = Join-Path $Data ("dups_{0}.txt" -f $date)
    $dupLines | Set-Content -Path $dupFile -Encoding UTF8
    Write-Log ("WARN dup={0} pairs on {1} -> {2}" -f $dupLines.Count, $date, $dupFile)
    foreach ($dl in $dupLines) { Write-Log ("  " + $dl.Trim()) }
} else {
    Write-Log ("dup=0 on {0}" -f $date)
}
# cross-check: agent reported a count but printed no pairs
if ($out -match 'dup=(\d+)' -and [int]$Matches[1] -gt 0 -and $dupLines.Count -eq 0) {
    Write-Log ("WARN agent reported dup=" + $Matches[1] + " but printed no DUP: pairs")
}

if ($ok) {
    $endTime = Get-Date
    [pscustomobject]@{
        lastRun = $endTime.ToString('yyyy-MM-ddTHH:mm:ss')
        today   = $date
        count   = ($count + 1)
    } | ConvertTo-Json -Depth 3 | Set-Content -Path $StateFile -Encoding UTF8
    Write-Log ("DONE {0} run={1}" -f $date, ($count + 1))
} else {
    Write-Log "FAIL claude rc=$rc"
}
