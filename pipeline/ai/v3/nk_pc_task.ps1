# Ability-trial pages: read on the PC, seal and put on release v3-nk-html (2026-11-02). Daily 10:30 and 13:30 (the job runs 14:30).
# Register: powershell -ExecutionPolicy Bypass -File nk_pc_task.ps1 -Register
# Scripts are copied to C:\Users\kouki\nankan_ai\pc_tasks (work trees may be removed). ASCII only (PowerShell 5.1 reads ps1 as ANSI).
param([switch]$Register)
$home_ = 'C:\Users\kouki\nankan_ai\pc_tasks'
$log = Join-Path $home_ 'nk_pc_release.log'
if ($Register) {
    New-Item -ItemType Directory -Force $home_ | Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'nk_fetch.py'), (Join-Path $PSScriptRoot 'nk_pc_release.py'), $PSCommandPath $home_ -Force
    $a = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$home_\nk_pc_task.ps1`""
    $t = @((New-ScheduledTaskTrigger -Daily -At 10:30), (New-ScheduledTaskTrigger -Daily -At 13:30))
    $st = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName 'V3_NkHtml' -Action $a -Trigger $t -Settings $st -Force | Out-Null
    "registered: V3_NkHtml (daily 10:30, 13:30) scripts in $home_"
    return
}
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -Append -Encoding utf8 $log
$env:PATH = "C:\Program Files\Git\mingw64\bin;$env:PATH"   # openssl
& py -3.12 -X utf8 (Join-Path $home_ 'nk_pc_release.py') 2>&1 | Out-File -Append -Encoding utf8 $log
