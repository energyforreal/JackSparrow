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
python $PythonScript

# Exit with the same code as Python script
exit $LASTEXITCODE

