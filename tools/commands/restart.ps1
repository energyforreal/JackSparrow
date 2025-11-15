# Restart all JackSparrow services (PowerShell)

Write-Host "Restarting JackSparrow Trading Agent..." -ForegroundColor Green
Write-Host ""

# Stop services (kill processes)
Get-Process | Where-Object { $_.ProcessName -like "*python*" -or $_.ProcessName -like "*node*" } | Where-Object { $_.CommandLine -like "*api.main*" -or $_.CommandLine -like "*intelligent_agent*" -or $_.CommandLine -like "*next dev*" } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Services stopped" -ForegroundColor Yellow
Start-Sleep -Seconds 2

# Start services
& "$PSScriptRoot\start.ps1"

