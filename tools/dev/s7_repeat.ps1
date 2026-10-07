<#
S7 repeatability test: launch the game N times with quick boot and record, per run, the time from
launch to "quickboot: done", the distance to the fog gate, and a screenshot.

  pwsh tools/dev/s7_repeat.ps1 [-Runs 3]

Results: scratch\runs\s7-<timestamp>\ (logs, screenshots, summary.txt).
#>
param([int]$Runs = 3)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Game = "$Root\tools\dev\game.ps1"
$Log = "$Root\scratch\mod\logs\er_apex.log"
$Out = "$Root\scratch\runs\s7-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
New-Item -ItemType Directory -Force $Out | Out-Null
$summary = @()
for ($i = 1; $i -le $Runs; $i++) {
    pwsh -NoProfile -File $Game stop | Out-Null
    Start-Sleep -Seconds 3
    # the previous run's log must not count (the DLL starts a fresh one when it loads)
    Remove-Item $Log -ErrorAction SilentlyContinue
    $t0 = Get-Date
    pwsh -NoProfile -File $Game start
    $result = $null
    while (((Get-Date) - $t0).TotalSeconds -lt 180) {
        Start-Sleep -Milliseconds 500
        if (Test-Path $Log) {
            $hit = Select-String -Path $Log -Pattern 'quickboot: (done|FAILED)' | Select-Object -First 1
            if ($hit) { $result = $hit.Line; break }
        }
    }
    $wall = [int]((Get-Date) - $t0).TotalSeconds
    Start-Sleep -Seconds 3
    try { pwsh -NoProfile -File $Game shot "s7-repeat-$i" | Out-Null; Copy-Item "$Root\scratch\shots\s7-repeat-$i.png" $Out } catch {}
    Copy-Item $Log "$Out\er_apex-run$i.log" -ErrorAction SilentlyContinue
    $line = "run ${i}: wall ${wall} s from me3 start; $(if ($result) { $result } else { 'NO RESULT within 180 s' })"
    $summary += $line
    Write-Output $line
}
pwsh -NoProfile -File $Game stop | Out-Null
$summary | Set-Content "$Out\summary.txt"
"results in $Out"
