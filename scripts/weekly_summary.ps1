# Weekly: build a structured summary of the week (Monday..Sunday) from the
# Obsidian diary blocks written by daily_worklog.ps1, and write it into
# ObsidianVault\07-日记\<YYYY>-W<NN>_周总结.md.
#
# Week node is SUNDAY (user decision 2026-11-05): the week runs Monday 00:00
# through Sunday 23:59. The daily trigger fires every day at 22:50 and the
# script decides whether there is work to do, so a missed Sunday (sleep /
# power off) is caught up on the next logon or wake.
#
# ASCII comments on purpose (non-ASCII comments can swallow newlines on this box).
param([string]$WeekEnd = '', [switch]$Force, [switch]$DryRun)

$ErrorActionPreference = 'Continue'
# child process (python / claude) emits UTF-8, not GBK
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'wl_config.ps1')

$HomeDir = $env:USERPROFILE
$Project = $WlRoot
$Scripts = Join-Path $Project 'scripts'
$Logs = Join-Path $Project 'logs'
$Data = Join-Path $Project 'data'
$Log = Join-Path $Logs 'weekly_summary.log'
$StateFile = Join-Path $Data 'weekly_state.json'
$Vault = Wl-Vault
$DiaryDir = Wl-WeeklyDir
$claudeCfg = Wl-ClaudeCfg
$ClaudeCmd = Wl-Get $claudeCfg 'command' 'claude'
$CostScript = Wl-Expand (Wl-Get $claudeCfg 'cost_script' '')
$ExtractScript = Join-Path $Scripts 'weekly_extract.py'
$Lang = Wl-Get $WlCfg 'prompt_lang' 'zh'
$PromptFile = Join-Path $Scripts ('weekly_prompt.{0}.md' -f $Lang)

foreach ($d in @($Logs, $Data, $DiaryDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Write-Log([string]$msg) {
    $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

$Py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }

# NOTE: PS variables are case-insensitive, so a local $weekEnd would overwrite the
# -WeekEnd parameter. Capture the manual flag first and use $wkEnd from here on.
$isManual = [bool]$WeekEnd
$now = Get-Date

# Resolve the target week: the one whose Sunday is $wkEnd (Monday..Sunday).
if ($isManual) {
    $anchor = [datetime]::ParseExact($WeekEnd, 'yyyy-MM-dd', $null)
} else {
    $anchor = $now.Date
}
$dow = [int]$anchor.DayOfWeek          # Sunday=0, Monday=1, ... Saturday=6
$wkEnd = $anchor.AddDays((7 - $dow) % 7)
if ($wkEnd.Date -gt $now.Date) { $wkEnd = $wkEnd.AddDays(-7) }
# Before 22:00 on a Sunday the current week is not finished yet -> use the previous one.
if (-not $isManual -and $dow -eq 0 -and $now.Hour -lt 22) { $wkEnd = $wkEnd.AddDays(-7) }
$wkStart = $wkEnd.AddDays(-6)

# ISO week key. ISOWeek class does not exist in .NET Framework (PS 5.1), so derive
# it from the Thursday of the week (Monday-first, first-four-day rule == ISO).
$cal = [System.Globalization.CultureInfo]::InvariantCulture.Calendar
$thu = $wkEnd.AddDays(-3)
$weekNum = $cal.GetWeekOfYear($thu, [System.Globalization.CalendarWeekRule]::FirstFourDayWeek, [System.DayOfWeek]::Monday)
$weekKey = '{0}-W{1:D2}' -f $thu.Year, $weekNum

$outFile = Join-Path $DiaryDir ('{0}_周总结.md' -f $weekKey)
$evPath = Join-Path $Data ('weekly_evidence_{0}.md' -f $weekKey)
$dateFrom = $wkStart.ToString('yyyy-MM-dd')
$dateTo = $wkEnd.ToString('yyyy-MM-dd')

# ---- skip check: only regenerate when the stored run does not already cover the end of the week ----
# A Sunday 22:50 run does not cover Sunday 22:50-23:59, so one refresh on the next
# day is allowed (generatedAt >= Monday 00:00 means done).
$stateWeek = ''
$stateAt = $null
if (Test-Path $StateFile) {
    try {
        $st = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $stateWeek = [string]$st.week
        if ($st.generatedAt) { $stateAt = [datetime]::Parse($st.generatedAt) }
    } catch { }
}
$coveredUntil = $wkEnd.Date.AddDays(1)   # Monday 00:00
$needRun = $true
if (-not $Force -and (Test-Path $outFile) -and $stateWeek -eq $weekKey -and $stateAt -and $stateAt -ge $coveredUntil) {
    $needRun = $false
}

Write-Log ("PLAN week={0} range={1}..{2} manual={3} force={4} needRun={5} last={6}@{7}" -f `
    $weekKey, $dateFrom, $dateTo, $isManual, [bool]$Force, $needRun, $stateWeek, $stateAt)
if (-not $needRun) { Write-Log ("SKIP {0} already summarized" -f $weekKey); exit 0 }

Set-Location $HomeDir

# ---- 1. extract the week's diary evidence ----
Remove-Item $evPath -Force -ErrorAction SilentlyContinue
$evOut = & $Py $ExtractScript --week-end $dateTo --out $evPath 2>&1 | Out-String
$rc = $LASTEXITCODE
Write-Log ("EXTRACT rc={0} :: {1}" -f $rc, $evOut.Trim())
if ($rc -eq 2) { Write-Log ("SKIP {0} no diary entries in range" -f $weekKey); exit 0 }
if ($rc -ne 0) { Write-Log 'FAIL extract'; exit 1 }

$itemCount = ''
if ($evOut -match 'items=(\d+)') { $itemCount = $Matches[1] }

if ($DryRun) {
    $evLen = (Get-Item $evPath).Length
    Write-Log ("DRYRUN week={0} range={1}..{2} items={3} evidence={4} bytes -> {5}" -f `
        $weekKey, $dateFrom, $dateTo, $itemCount, $evLen, $outFile)
    exit 0
}

# ---- 2. call claude -p ----
$claude = $ClaudeCmd
if (-not (Test-Path $claude)) { $claude = Join-Path $env:APPDATA 'npm\claude.cmd' }
if (-not (Test-Path $claude)) { $claude = 'claude' }

$generatedAt = (Get-Date -Format 'yyyy-MM-dd HH:mm')
$instr = ('Read the instruction file {0} and follow it strictly. Evidence file: {1}. Output file: {2}. Week: {3}. Range: {4} ~ {5}. GeneratedAt: {6}. Print only the final result line.' `
    -f $PromptFile, $evPath, $outFile, $weekKey, $dateFrom, $dateTo, $generatedAt)

$tmpOut = Join-Path $env:TEMP 'weekly_stdout.txt'
$tmpErr = Join-Path $env:TEMP 'weekly_stderr.txt'

function Get-TodayCny([string]$d) {
    try {
        $raw = (& $Py $CostScript --date $d --json) | Out-String
        $o = $raw.Trim() | ConvertFrom-Json
        return [double]$o.total
    } catch { return -1 }
}
$costDate = Get-Date -Format 'yyyy-MM-dd'
$preCny = Get-TodayCny $costDate

$argStr = @(
    '-p', ('"{0}"' -f $instr),
    '--permission-mode', 'auto',
    '--allowedTools', 'Read,Write,Glob,Grep'
) -join ' '

$proc = Start-Process -FilePath $claude -ArgumentList $argStr -NoNewWindow -PassThru `
    -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
$timeoutMs = 600000
if (-not $proc.WaitForExit($timeoutMs)) {
    try { $proc.Kill() } catch { }
    Write-Log ("FAIL claude timeout after {0} ms" -f $timeoutMs)
    exit 1
}
$rc = $proc.ExitCode
$out = ''
if (Test-Path $tmpOut) { $out = (Get-Content $tmpOut -Raw -Encoding UTF8) }
$tail = $out.Trim()
if ($tail.Length -gt 800) { $tail = $tail.Substring($tail.Length - 800) }

# success is judged by the file on disk, not by the process exit code
$fileOk = $false
if (Test-Path $outFile) {
    $txt = Get-Content $outFile -Raw -Encoding UTF8
    $fileOk = ($txt -match 'type:\s*(周总结|weekly-summary)') -and ($txt -match 'generated_at:') -and ($txt -match '## (一、本周概览|1\. Overview)')
}
$ok = ($tail -match 'WEEK_DONE') -and $fileOk
if ($tail -match 'WEEK_NODATA') { $ok = $false }

$postCny = Get-TodayCny $costDate
if ($preCny -ge 0 -and $postCny -ge 0) {
    $costMsg = ('cost=CNY {0:N3} (day total CNY {1:N2})' -f ($postCny - $preCny), $postCny)
} else {
    $costMsg = 'cost=CNY n/a'
}
Write-Log ("CLAUDE rc={0} ok={1} file={2} {3} :: {4}" -f $rc, $ok, $fileOk, $costMsg, $tail)

if ($ok) {
    [pscustomobject]@{
        week        = $weekKey
        range       = ('{0}..{1}' -f $dateFrom, $dateTo)
        generatedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
        items       = $itemCount
        file        = $outFile
    } | ConvertTo-Json -Depth 3 | Set-Content -Path $StateFile -Encoding UTF8
    Write-Log ("DONE week={0} items={1} -> {2}" -f $weekKey, $itemCount, $outFile)
} else {
    Write-Log ("FAIL claude rc={0} week={1}" -f $rc, $weekKey)
    exit 1
}
