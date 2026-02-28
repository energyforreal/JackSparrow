# Run comprehensive system audit (PowerShell)

$ErrorActionPreference = "Continue"

Write-Host "Running comprehensive system audit..." -ForegroundColor Green
Write-Host ""

# Get script directory for proper path resolution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Check if Python is available
$pythonCmd = $null
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} else {
    Write-Host "❌ Python not found. Cannot run comprehensive audit." -ForegroundColor Red
    exit 1
}

# Check if comprehensive audit script exists
$auditScript = Join-Path $ProjectRoot "scripts\comprehensive_audit.py"
if (!(Test-Path $auditScript)) {
    Write-Host "❌ Comprehensive audit script not found at $auditScript" -ForegroundColor Red
    Write-Host "Falling back to basic audit..." -ForegroundColor Yellow
    Write-Host ""

    # Fallback to basic audit (original functionality)
    $LogsDir = Join-Path $ProjectRoot "logs"
    New-Item -ItemType Directory -Force -Path "$LogsDir\audit" | Out-Null
    $AUDIT_LOG = Join-Path $LogsDir "audit\audit_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

    "Audit started at $(Get-Date)" | Out-File -FilePath $AUDIT_LOG -Encoding UTF8
    "================================" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8
    "" | Out-File -FilePath $AUDIT_LOG -Append -Encoding UTF8

    Write-Host "Checking Python code formatting..." -ForegroundColor Yellow
    if (Get-Command black -ErrorAction SilentlyContinue) {
        if (Test-Path "$ProjectRoot\backend") {
            Push-Location "$ProjectRoot\backend"
            try {
                $result = & black --check . 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✓ Backend formatting OK" -ForegroundColor Green
                } else {
                    Write-Host "  ⚠ Backend formatting issues found" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "  ⚠ Backend formatting check failed: $_" -ForegroundColor Yellow
            }
            Pop-Location
        }
    } else {
        Write-Host "  ⚠ black not installed, skipping format check" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Basic audit complete. Results saved to $AUDIT_LOG" -ForegroundColor Green
    exit 0
}

# Run comprehensive audit
Write-Host "Executing comprehensive audit script..." -ForegroundColor Green
Write-Host ""

# Parse command line arguments
$auditArgs = @()
if ($args -contains "--verbose" -or $args -contains "-v") {
    $auditArgs += "--verbose"
}
if ($args -contains "--quick" -or $args -contains "-q") {
    $auditArgs += "--quick"
}

# Change to project root directory and run the audit
Push-Location $ProjectRoot
try {
    & $pythonCmd scripts/comprehensive_audit.py @auditArgs
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Comprehensive audit complete!" -ForegroundColor Green

