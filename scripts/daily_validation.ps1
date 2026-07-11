# Daily validation — JackSparrow continuous validation pipeline
# Register in Windows Task Scheduler (daily 06:00 UTC recommended):
#   Program: powershell.exe
#   Arguments: -NoProfile -ExecutionPolicy Bypass -File "D:\ATTRAL\Projects\Trading Agent 2\scripts\daily_validation.ps1"
#   Start in: D:\ATTRAL\Projects\Trading Agent 2
#
# Weekly (Sundays): pass -Weekly to include DQI + thesis miss analysis

param(
    [switch]$Weekly
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "=== JackSparrow daily validation $(Get-Date -Format o) ==="

$args = @("tools/commands/phase3_daily_forensics.py", "--workstream", "shadow")
if ($Weekly) {
    $args += "--weekly"
}

python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "=== Daily validation complete ==="
