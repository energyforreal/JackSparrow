# Automated test script for Docker hot reload functionality (PowerShell)
# Tests that code changes trigger automatic reloads/restarts

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Test results
$script:TESTS_PASSED = 0
$script:TESTS_FAILED = 0
$script:TEST_RESULTS = @()

# Cleanup function
function Cleanup {
    Write-Host "`nCleaning up test files..." -ForegroundColor Yellow
    # Remove test comments from files
    $backendFile = "backend\api\main.py"
    $agentFile = "agent\core\intelligent_agent.py"
    
    if (Test-Path $backendFile) {
        $content = Get-Content $backendFile | Where-Object { $_ -notmatch "HOT_RELOAD_TEST" }
        $content | Set-Content $backendFile
    }
    
    if (Test-Path $agentFile) {
        $content = Get-Content $agentFile | Where-Object { $_ -notmatch "HOT_RELOAD_TEST" }
        $content | Set-Content $agentFile
    }
    
    Write-Host "Cleanup complete" -ForegroundColor Green
}

# Register cleanup on exit
Register-EngineEvent PowerShell.Exiting -Action { Cleanup } | Out-Null

# Function to check if services are running
function Test-ServicesRunning {
    $services = docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps --services --filter "status=running" 2>$null
    return $services -ne $null -and $services.Count -gt 0
}

# Function to wait for service to be ready
function Wait-ForService {
    param([string]$Service)
    $maxAttempts = 30
    $attempt = 0
    
    Write-Host "Waiting for $Service to be ready..." -ForegroundColor Blue
    while ($attempt -lt $maxAttempts) {
        $status = docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps $Service 2>$null
        if ($status -match "Up") {
            Start-Sleep -Seconds 2
            return $true
        }
        $attempt++
        Start-Sleep -Seconds 1
    }
    return $false
}

# Function to check logs for reload message
function Test-ReloadMessage {
    param(
        [string]$Service,
        [string]$Pattern,
        [int]$Timeout = 10
    )
    
    $startTime = Get-Date
    while (((Get-Date) - $startTime).TotalSeconds -lt $Timeout) {
        $logs = docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs --tail=50 $Service 2>$null
        if ($logs -match $Pattern) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Test function
function Invoke-Test {
    param(
        [string]$TestName,
        [scriptblock]$TestFunc
    )
    
    Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "Test: $TestName" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    
    try {
        if (& $TestFunc) {
            Write-Host "✓ PASSED: $TestName" -ForegroundColor Green
            $script:TESTS_PASSED++
            $script:TEST_RESULTS += "PASS: $TestName"
            return $true
        } else {
            Write-Host "✗ FAILED: $TestName" -ForegroundColor Red
            $script:TESTS_FAILED++
            $script:TEST_RESULTS += "FAIL: $TestName"
            return $false
        }
    } catch {
        Write-Host "✗ FAILED: $TestName - $($_.Exception.Message)" -ForegroundColor Red
        $script:TESTS_FAILED++
        $script:TEST_RESULTS += "FAIL: $TestName - Error"
        return $false
    }
}

# Test 1: Backend hot reload
function Test-BackendReload {
    Write-Host "Making change to backend file..." -ForegroundColor Blue
    $testComment = "# HOT_RELOAD_TEST $(Get-Date -Format 'yyyyMMddHHmmss')"
    Add-Content -Path "backend\api\main.py" -Value $testComment
    
    Write-Host "Waiting for backend reload..." -ForegroundColor Blue
    if (Test-ReloadMessage -Service "backend" -Pattern "Detected file change|Reloading") {
        Write-Host "Backend reload detected" -ForegroundColor Green
        
        # Verify service is still healthy
        Start-Sleep -Seconds 2
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            Write-Host "Backend health check failed after reload" -ForegroundColor Red
            return $false
        }
    } else {
        Write-Host "Backend reload not detected in logs" -ForegroundColor Red
        return $false
    }
}

# Test 2: Agent hot reload
function Test-AgentReload {
    Write-Host "Making change to agent file..." -ForegroundColor Blue
    $testComment = "# HOT_RELOAD_TEST $(Get-Date -Format 'yyyyMMddHHmmss')"
    Add-Content -Path "agent\core\intelligent_agent.py" -Value $testComment
    
    Write-Host "Waiting for agent restart..." -ForegroundColor Blue
    if (Test-ReloadMessage -Service "agent" -Pattern "file_changed|restarting agent|Starting agent process") {
        Write-Host "Agent restart detected" -ForegroundColor Green
        
        # Verify agent is still running
        Start-Sleep -Seconds 3
        $status = docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps agent 2>$null
        if ($status -match "Up") {
            return $true
        } else {
            Write-Host "Agent not running after restart" -ForegroundColor Red
            return $false
        }
    } else {
        Write-Host "Agent restart not detected in logs" -ForegroundColor Red
        return $false
    }
}

# Test 3: Verify file watcher is running
function Test-FileWatcherRunning {
    Write-Host "Checking if file watcher is running..." -ForegroundColor Blue
    $processes = docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T agent ps aux 2>$null
    if ($processes -match "dev_watcher") {
        Write-Host "File watcher process found" -ForegroundColor Green
        return $true
    } else {
        Write-Host "File watcher process not found (may be running as main process)" -ForegroundColor Yellow
        # Check logs for watcher startup message
        $logs = docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs agent 2>$null
        if ($logs -match "watcher_ready|File watcher is ready") {
            return $true
        } else {
            Write-Host "File watcher not detected" -ForegroundColor Red
            return $false
        }
    }
}

# Test 4: Verify watchdog is installed
function Test-WatchdogInstalled {
    Write-Host "Checking if watchdog is installed..." -ForegroundColor Blue
    $packages = docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec -T agent pip list 2>$null
    if ($packages -match "watchdog") {
        Write-Host "Watchdog is installed" -ForegroundColor Green
        return $true
    } else {
        Write-Host "Watchdog is not installed" -ForegroundColor Red
        return $false
    }
}

# Main test execution
function Main {
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    Write-Host "Docker Hot Reload Automated Test Suite" -ForegroundColor Green
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
    
    # Check if services are running
    if (-not (Test-ServicesRunning)) {
        Write-Host "Services are not running. Starting services..." -ForegroundColor Yellow
        Write-Host "Please start services manually first:" -ForegroundColor Blue
        Write-Host "  .\scripts\docker\dev-start.ps1 -Build" -ForegroundColor Blue
        Write-Host "  or" -ForegroundColor Blue
        Write-Host "  make docker-dev" -ForegroundColor Blue
        exit 1
    }
    
    Write-Host "Services are running. Starting tests..." -ForegroundColor Green
    
    # Wait for services to be ready
    Wait-ForService -Service "backend" | Out-Null
    if (-not $?) {
        Write-Host "Warning: Backend may not be ready" -ForegroundColor Yellow
    }
    
    Wait-ForService -Service "agent" | Out-Null
    if (-not $?) {
        Write-Host "Warning: Agent may not be ready" -ForegroundColor Yellow
    }
    
    # Run tests
    Invoke-Test -TestName "Watchdog Installation" -TestFunc ${function:Test-WatchdogInstalled} | Out-Null
    Invoke-Test -TestName "File Watcher Running" -TestFunc ${function:Test-FileWatcherRunning} | Out-Null
    Invoke-Test -TestName "Backend Hot Reload" -TestFunc ${function:Test-BackendReload} | Out-Null
    Invoke-Test -TestName "Agent Hot Reload" -TestFunc ${function:Test-AgentReload} | Out-Null
    
    # Print summary
    Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "Test Summary" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    
    foreach ($result in $script:TEST_RESULTS) {
        if ($result -match "PASS:") {
            Write-Host $result -ForegroundColor Green
        } else {
            Write-Host $result -ForegroundColor Red
        }
    }
    
    $total = $script:TESTS_PASSED + $script:TESTS_FAILED
    Write-Host "`nTotal: $total tests" -ForegroundColor Cyan
    Write-Host "Passed: $($script:TESTS_PASSED)" -ForegroundColor Green
    Write-Host "Failed: $($script:TESTS_FAILED)" -ForegroundColor Red
    
    if ($script:TESTS_FAILED -eq 0) {
        Write-Host "`n✓ All tests passed!" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "`n✗ Some tests failed" -ForegroundColor Red
        exit 1
    }
}

# Run main function
Main

