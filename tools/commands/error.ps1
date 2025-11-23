# Quick error diagnostic (PowerShell)

$ErrorActionPreference = "Continue"

Write-Host "JackSparrow Error Diagnostics" -ForegroundColor Green
Write-Host "==============================" -ForegroundColor Green
Write-Host ""

# Get script directory for proper path resolution
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogsDir = Join-Path $ProjectRoot "logs"

# Create error log directory
New-Item -ItemType Directory -Force -Path "$LogsDir\error" | Out-Null
$ERROR_LOG = Join-Path $LogsDir "error\summary_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Initialize log file
"" | Out-File -FilePath $ERROR_LOG -Encoding UTF8

# Check service status using PID files first
Write-Host "Service Status:" -ForegroundColor Yellow

# Check Backend
$backendStatus = "✗ Backend not running"
if (Test-Path "$LogsDir\backend.pid") {
    $backendPid = Get-Content "$LogsDir\backend.pid" -ErrorAction SilentlyContinue
    if ($backendPid) {
        $backendProcess = Get-Process -Id $backendPid -ErrorAction SilentlyContinue
        if ($backendProcess) {
            $backendStatus = "✓ Backend running (PID: $backendPid)"
            Write-Host "  $backendStatus" -ForegroundColor Green
        } else {
            Write-Host "  $backendStatus" -ForegroundColor Red
        }
    } else {
        Write-Host "  $backendStatus" -ForegroundColor Red
    }
} else {
    # Fallback: Check by command line using Get-CimInstance
    $backendProcs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*api.main*"
    }
    if ($backendProcs) {
        $backendPid = $backendProcs[0].ProcessId
        $backendStatus = "✓ Backend running (PID: $backendPid)"
        Write-Host "  $backendStatus" -ForegroundColor Green
    } else {
        Write-Host "  $backendStatus" -ForegroundColor Red
    }
}
$backendStatus | Out-File -FilePath $ERROR_LOG -Append -Encoding UTF8

# Check Agent
$agentStatus = "✗ Agent not running"
if (Test-Path "$LogsDir\agent.pid") {
    $agentPid = Get-Content "$LogsDir\agent.pid" -ErrorAction SilentlyContinue
    if ($agentPid) {
        $agentProcess = Get-Process -Id $agentPid -ErrorAction SilentlyContinue
        if ($agentProcess) {
            $agentStatus = "✓ Agent running (PID: $agentPid)"
            Write-Host "  $agentStatus" -ForegroundColor Green
        } else {
            Write-Host "  $agentStatus" -ForegroundColor Red
        }
    } else {
        Write-Host "  $agentStatus" -ForegroundColor Red
    }
} else {
    # Fallback: Check by command line using Get-CimInstance
    $agentProcs = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -like "*intelligent_agent*"
    }
    if ($agentProcs) {
        $agentPid = $agentProcs[0].ProcessId
        $agentStatus = "✓ Agent running (PID: $agentPid)"
        Write-Host "  $agentStatus" -ForegroundColor Green
    } else {
        Write-Host "  $agentStatus" -ForegroundColor Red
    }
}
$agentStatus | Out-File -FilePath $ERROR_LOG -Append -Encoding UTF8

# Check recent errors
Write-Host ""
Write-Host "Recent Errors (last 20 lines):" -ForegroundColor Yellow
if (Test-Path $LogsDir) {
    $errorLines = Get-ChildItem -Path $LogsDir -Filter "*.log" -Recurse -ErrorAction SilentlyContinue | 
        Select-String -Pattern "error|exception|traceback" -CaseSensitive:$false -ErrorAction SilentlyContinue | 
        Select-Object -First 20
    if ($errorLines) {
        foreach ($line in $errorLines) {
            Write-Host "  $($line.Line)" -ForegroundColor Yellow
            $line.Line | Out-File -FilePath $ERROR_LOG -Append -Encoding UTF8
        }
    } else {
        Write-Host "  No errors found in logs" -ForegroundColor Gray
        "No errors found in logs" | Out-File -FilePath $ERROR_LOG -Append -Encoding UTF8
    }
} else {
    Write-Host "  Logs directory not found" -ForegroundColor Yellow
    "Logs directory not found" | Out-File -FilePath $ERROR_LOG -Append -Encoding UTF8
}

Write-Host ""
Write-Host "Diagnostics saved to $ERROR_LOG" -ForegroundColor Green

