# Run system audit (PowerShell)

Write-Host "Running system audit..." -ForegroundColor Green
Write-Host ""

# Create audit log directory
New-Item -ItemType Directory -Force -Path logs/audit | Out-Null
$AUDIT_LOG = "logs/audit/audit_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Check Python formatting
Write-Host "Checking Python code formatting..." -ForegroundColor Yellow
if (Get-Command black -ErrorAction SilentlyContinue) {
    cd backend
    black --check . 2>&1 | Out-File -Append ..\$AUDIT_LOG
    cd ..
} else {
    Write-Host "  ⚠ black not installed, skipping format check" -ForegroundColor Yellow
}

# Check health
Write-Host "Checking service health..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing | Out-File -Append $AUDIT_LOG
} catch {
    Write-Host "  ⚠ Backend health check failed" -ForegroundColor Yellow
}

# Check logs for errors
Write-Host "Checking logs for errors..." -ForegroundColor Yellow
Get-ChildItem -Path logs -Filter "*.log" -Recurse | Select-String -Pattern "ERROR|WARN" | Select-Object -First 20 | Out-File -Append $AUDIT_LOG

Write-Host ""
Write-Host "Audit complete. Results saved to $AUDIT_LOG" -ForegroundColor Green

