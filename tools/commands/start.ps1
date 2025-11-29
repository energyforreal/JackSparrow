<#
Start all JackSparrow services (PowerShell wrapper).
Delegates to the Python-based parallel startup manager.
#>

$ErrorActionPreference = "Stop"

# Resolve key paths
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonScript = Join-Path $ScriptDir "start_parallel.py"
$ServiceScript = Join-Path $ProjectRoot "tools\start-services.ps1"

# Ensure Python is available
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Python not found"
    }
} catch {
    Write-Host "Error: Python is required but not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python 3.11+ and ensure it's available in PATH." -ForegroundColor Yellow
    exit 1
}

# Try to ensure Redis/PostgreSQL via helper if available
if (Test-Path $ServiceScript) {
    Write-Host "Ensuring prerequisite services (PostgreSQL/Redis) are running..." -ForegroundColor Yellow
    try {
        & $ServiceScript
    } catch {
        Write-Host "Warning: Unable to run start-services.ps1 automatically. $_" -ForegroundColor Yellow
    }
    Write-Host ""
}

# Ensure Python and child processes flush immediately
$env:PYTHONUNBUFFERED = "1"

# Launch Python parallel manager
Write-Host "Launching parallel process manager..." -ForegroundColor Green
python $PythonScript

exit $LASTEXITCODE
