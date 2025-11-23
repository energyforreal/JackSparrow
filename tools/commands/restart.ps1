# Restart all JackSparrow services (PowerShell)

$ErrorActionPreference = "Continue"

Write-Host "Restarting JackSparrow Trading Agent..." -ForegroundColor Green
Write-Host ""

# Get script directory for proper path resolution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogsDir = Join-Path $ProjectRoot "logs"

# Stop services using PID files first
Write-Host "Stopping services..." -ForegroundColor Yellow

if (Test-Path "$LogsDir\backend.pid") {
    $backendPid = Get-Content "$LogsDir\backend.pid" -ErrorAction SilentlyContinue
    if ($backendPid) {
        Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped Backend (PID: $backendPid)" -ForegroundColor Gray
    }
    Remove-Item "$LogsDir\backend.pid" -ErrorAction SilentlyContinue
}

if (Test-Path "$LogsDir\agent.pid") {
    $agentPid = Get-Content "$LogsDir\agent.pid" -ErrorAction SilentlyContinue
    if ($agentPid) {
        Stop-Process -Id $agentPid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped Agent (PID: $agentPid)" -ForegroundColor Gray
    }
    Remove-Item "$LogsDir\agent.pid" -ErrorAction SilentlyContinue
}

if (Test-Path "$LogsDir\frontend.pid") {
    $frontendPid = Get-Content "$LogsDir\frontend.pid" -ErrorAction SilentlyContinue
    if ($frontendPid) {
        Stop-Process -Id $frontendPid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped Frontend (PID: $frontendPid)" -ForegroundColor Gray
    }
    Remove-Item "$LogsDir\frontend.pid" -ErrorAction SilentlyContinue
}

# Fallback: Stop processes by command line using Get-CimInstance
$processes = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "python.exe" -or $_.Name -eq "node.exe") -and
    ($_.CommandLine -like "*api.main*" -or $_.CommandLine -like "*intelligent_agent*" -or $_.CommandLine -like "*next dev*")
}

foreach ($proc in $processes) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "  Stopped process (PID: $($proc.ProcessId))" -ForegroundColor Gray
}

Write-Host "Services stopped" -ForegroundColor Yellow
Start-Sleep -Seconds 2

# Start services
Write-Host ""
& "$ScriptDir\start.ps1"

