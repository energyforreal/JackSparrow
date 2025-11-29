# Wrapper script to run audit and display results
$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

# Run the audit script
& "$ProjectRoot\tools\commands\audit.ps1"

# Wait a moment for file to be written
Start-Sleep -Seconds 1

# Find and display the latest audit log
$auditDir = Join-Path $ProjectRoot "logs\audit"
if (Test-Path $auditDir) {
    $latestLog = Get-ChildItem -Path $auditDir -Filter "*.log" -ErrorAction SilentlyContinue | 
                 Sort-Object LastWriteTime -Descending | 
                 Select-Object -First 1
    
    if ($latestLog) {
        Write-Host "`n=== Audit Report ===" -ForegroundColor Cyan
        Write-Host "File: $($latestLog.FullName)`n" -ForegroundColor Gray
        Get-Content $latestLog.FullName
    } else {
        Write-Host "No audit log file found" -ForegroundColor Yellow
    }
} else {
    Write-Host "Audit directory not found" -ForegroundColor Yellow
}
