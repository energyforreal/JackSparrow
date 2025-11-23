# Run system audit (PowerShell)

$ErrorActionPreference = "Continue"

Write-Host "Running system audit..." -ForegroundColor Green
Write-Host ""

# Get script directory for proper path resolution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogsDir = Join-Path $ProjectRoot "logs"

# Create audit log directory
New-Item -ItemType Directory -Force -Path "$LogsDir\audit" | Out-Null
$AUDIT_LOG = Join-Path $LogsDir "audit\audit_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Initialize audit log
"Audit started at $(Get-Date)" | Out-File -FilePath $AUDIT_LOG -Encoding UTF8
"================================" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8
"" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8

# Check Python formatting
Write-Host "Checking Python code formatting..." -ForegroundColor Yellow
if (Get-Command black -ErrorAction SilentlyContinue) {
    # Check backend
    if (Test-Path "$ProjectRoot\backend") {
        Push-Location "$ProjectRoot\backend"
        try {
            $backendResult = black --check . 2>&1
            $backendResult | Out-File -Append $AUDIT_LOG -Encoding UTF8
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✓ Backend formatting OK" -ForegroundColor Green
            } else {
                Write-Host "  ⚠ Backend formatting issues found" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "  ⚠ Backend formatting check failed: $_" -ForegroundColor Yellow
            "Backend formatting check failed: $_" | Out-File -Append $AUDIT_LOG -Encoding UTF8
        }
        Pop-Location
    } else {
        Write-Host "  ⚠ Backend directory not found" -ForegroundColor Yellow
        "Backend directory not found" | Out-File -Append $AUDIT_LOG -Encoding UTF8
    }
    
    # Check agent
    if (Test-Path "$ProjectRoot\agent") {
        Push-Location "$ProjectRoot\agent"
        try {
            $agentResult = black --check . 2>&1
            $agentResult | Out-File -Append $AUDIT_LOG -Encoding UTF8
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✓ Agent formatting OK" -ForegroundColor Green
            } else {
                Write-Host "  ⚠ Agent formatting issues found" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "  ⚠ Agent formatting check failed: $_" -ForegroundColor Yellow
            "Agent formatting check failed: $_" | Out-File -Append $AUDIT_LOG -Encoding UTF8
        }
        Pop-Location
    } else {
        Write-Host "  ⚠ Agent directory not found" -ForegroundColor Yellow
        "Agent directory not found" | Out-File -Append $AUDIT_LOG -Encoding UTF8
    }
} else {
    Write-Host "  ⚠ black not installed, skipping format check" -ForegroundColor Yellow
    "black not installed" | Out-File -Append $AUDIT_LOG -Encoding UTF8
}

# Check health
Write-Host "Checking service health..." -ForegroundColor Yellow
try {
    $healthResponse = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -ErrorAction Stop
    $healthResponse.Content | Out-File -Append $AUDIT_LOG -Encoding UTF8
    Write-Host "  ✓ Backend health check passed" -ForegroundColor Green
} catch {
    Write-Host "  ⚠ Backend health check failed" -ForegroundColor Yellow
    "Backend health check failed: $_" | Out-File -Append $AUDIT_LOG -Encoding UTF8
}

# Check logs for errors
Write-Host "Checking logs for errors..." -ForegroundColor Yellow
if (Test-Path $LogsDir) {
    $logFiles = Get-ChildItem -Path $LogsDir -Filter "*.log" -Recurse -ErrorAction SilentlyContinue
    if ($logFiles) {
        $errorLines = $logFiles | Select-String -Pattern "ERROR|WARN" -ErrorAction SilentlyContinue | Select-Object -First 20
        if ($errorLines) {
            Write-Host "  ⚠ Found $($errorLines.Count) error/warning lines in logs" -ForegroundColor Yellow
            $errorLines | ForEach-Object { $_.Line } | Out-File -Append $AUDIT_LOG -Encoding UTF8
        } else {
            Write-Host "  ✓ No errors found in logs" -ForegroundColor Green
            "No errors found in logs" | Out-File -Append $AUDIT_LOG -Encoding UTF8
        }
    } else {
        Write-Host "  ⚠ No log files found" -ForegroundColor Yellow
        "No log files found" | Out-File -Append $AUDIT_LOG -Encoding UTF8
    }
} else {
    Write-Host "  ⚠ Logs directory not found" -ForegroundColor Yellow
    "Logs directory not found" | Out-File -Append $AUDIT_LOG -Encoding UTF8
}

"" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8
"Audit completed at $(Get-Date)" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8

Write-Host ""
Write-Host "Audit complete. Results saved to $AUDIT_LOG" -ForegroundColor Green

