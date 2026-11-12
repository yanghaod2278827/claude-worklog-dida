# Shared config for the PowerShell entry points. Dot-source it, do not run it:
#   . (Join-Path $PSScriptRoot 'wl_config.ps1')
# Then use $WlRoot / $WlCfg / Wl-Get / Wl-Expand.

$Script:WlRoot = Split-Path -Parent $PSScriptRoot
$Script:WlCfg = $null
$cfgFile = Join-Path $Script:WlRoot 'config.json'
if (Test-Path $cfgFile) {
    try { $Script:WlCfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
}

function Wl-Expand([string]$p) {
    if (-not $p) { return $p }
    return ($p -replace '^~', $env:USERPROFILE)
}

function Wl-Get($obj, [string]$name, $default) {
    if ($null -ne $obj) {
        $v = $obj.$name
        if ($null -ne $v -and "$v" -ne '') { return $v }
    }
    return $default
}

function Wl-Vault { Wl-Expand (Wl-Get $Script:WlCfg 'vault' (Join-Path $env:USERPROFILE 'ObsidianVault')) }
function Wl-DailyDir { Wl-Expand (Wl-Get $Script:WlCfg 'daily_note_dir' (Wl-Vault)) }
function Wl-WeeklyDir { Wl-Expand (Wl-Get $Script:WlCfg 'weekly_dir' (Join-Path (Wl-Vault) '07-日记')) }
function Wl-ScheduleCfg { Wl-Get $Script:WlCfg 'schedule' $null }
function Wl-DidaCfg { Wl-Get $Script:WlCfg 'dida' $null }
function Wl-ClaudeCfg { Wl-Get $Script:WlCfg 'claude' $null }
function Wl-TzOffset { Wl-Get $Script:WlCfg 'tz_offset' '+0800' }
