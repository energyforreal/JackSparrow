# Start all JackSparrow services (PowerShell)
# Uses Python-based parallel process manager for simultaneous startup

$ErrorActionPreference = "Stop"

# Get script directory for proper path resolution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Path to Python parallel startup script
$PythonScript = Join-Path $ScriptDir "start_parallel.py"

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
} catch {
    Write-Host "Error: Python is required but not found in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.11+ and ensure it's in your PATH" -ForegroundColor Yellow
    exit 1
}

# Execute Python script for parallel startup
Write-Host "Launching parallel process manager..." -ForegroundColor Green
# Ensure local services are up (Redis/PostgreSQL helper)
$serviceScript = Join-Path $ProjectRoot "tools\start-services.ps1"
if (Test-Path $serviceScript) {
    Write-Host "Ensuring Redis/PostgreSQL services are running..." -ForegroundColor Yellow
    try {
        & $serviceScript
    } catch {
        Write-Host "Warning: Unable to run start-services.ps1 automatically. $_" -ForegroundColor Yellow
    }
    Write-Host ""
}

python $PythonScript

# Exit with the same code as Python script
exit $LASTEXITCODE

