# Quick error diagnostic (PowerShell)

Write-Host "JackSparrow Error Diagnostics" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green
Write-Host ""

# Create error log directory
New-Item -ItemType Directory -Force -Path logs/error | Out-Null
$ERROR_LOG = "logs/error/summary_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Check service status
Write-Host "Service Status:" -ForegroundColor Yellow
$backendProcess = Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*api.main*" } -ErrorAction SilentlyContinue
if ($backendProcess) {
    Write-Host "  ✓ Backend running (PID: $($backendProcess.Id))" -ForegroundColor Green | Tee-Object -Append $ERROR_LOG
} else {
    Write-Host "  ✗ Backend not running" -ForegroundColor Red | Tee-Object -Append $ERROR_LOG
}

$agentProcess = Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*intelligent_agent*" } -ErrorAction SilentlyContinue
if ($agentProcess) {
    Write-Host "  ✓ Agent running (PID: $($agentProcess.Id))" -ForegroundColor Green | Tee-Object -Append $ERROR_LOG
} else {
    Write-Host "  ✗ Agent not running" -ForegroundColor Red | Tee-Object -Append $ERROR_LOG
}

# Check recent errors
Write-Host ""
Write-Host "Recent Errors (last 20 lines):" -ForegroundColor Yellow
Get-ChildItem -Path logs -Filter "*.log" -Recurse | Select-String -Pattern "error|exception|traceback" -CaseSensitive:$false | Select-Object -First 20 | Tee-Object -Append $ERROR_LOG | Out-Null

Write-Host ""
Write-Host "Diagnostics saved to $ERROR_LOG" -ForegroundColor Green

