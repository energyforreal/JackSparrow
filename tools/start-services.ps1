# Start required services for JackSparrow Trading Agent
# This script helps start PostgreSQL and Redis on Windows

Write-Host "Starting required services for JackSparrow Trading Agent..." -ForegroundColor Cyan
Write-Host ""

# Helper to test if a TCP port is accepting connections
function Test-Port {
    param(
        [string]$HostName = "localhost",
        [int]$Port = 6379,
        [int]$TimeoutMs = 2000
    )
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $wait = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $wait) {
            $client.Close()
            return $false
        }
        $client.EndConnect($async)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

# Redis
$redisPortOpen = Test-Port -HostName "localhost" -Port 6379
if ($redisPortOpen) {
    Write-Host "✓ Redis reachable on localhost:6379" -ForegroundColor Green
} else {
    Write-Host "Redis not reachable on localhost:6379. Attempting to start bundled server..." -ForegroundColor Yellow
    $redisPath = Join-Path $PSScriptRoot "..\redis-tmp\redis-server.exe"
    $redisConfig = Join-Path $PSScriptRoot "..\redis-tmp\redis.windows.conf"
    
    if (Test-Path $redisPath) {
        Start-Process -FilePath $redisPath -ArgumentList $redisConfig -WindowStyle Minimized
        Start-Sleep -Seconds 2
        if (Test-Port -HostName "localhost" -Port 6379) {
            Write-Host "✓ Redis server started" -ForegroundColor Green
            $redisPortOpen = $true
        } else {
            Write-Host "✗ Redis failed to start. Check redis-tmp folder or install Redis separately." -ForegroundColor Red
        }
    } else {
        Write-Host "✗ redis-server.exe not found at: $redisPath" -ForegroundColor Red
        Write-Host "  Install Redis or run via Docker: docker run -d -p 6379:6379 redis:7.2-alpine" -ForegroundColor Yellow
    }
}

Write-Host ""

# PostgreSQL
$postgresPortOpen = Test-Port -HostName "localhost" -Port 5432
if ($postgresPortOpen) {
    Write-Host "✓ PostgreSQL reachable on localhost:5432" -ForegroundColor Green
} else {
    Write-Host "PostgreSQL not reachable on localhost:5432. Attempting to start Windows service..." -ForegroundColor Yellow
    $postgresServices = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($postgresServices) {
        $service = $postgresServices | Select-Object -First 1
        try {
            Start-Service -Name $service.Name
            Start-Sleep -Seconds 2
            $postgresPortOpen = Test-Port -HostName "localhost" -Port 5432
            if ($postgresPortOpen) {
                Write-Host "✓ PostgreSQL service started: $($service.Name)" -ForegroundColor Green
            } else {
                Write-Host "✗ Service started but port 5432 still closed." -ForegroundColor Red
            }
        } catch {
            Write-Host "✗ Failed to start PostgreSQL service: $_" -ForegroundColor Red
            Write-Host "  Start it manually via Services app or run: net start $($service.Name)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "✗ PostgreSQL service not found." -ForegroundColor Red
        Write-Host "  Options:" -ForegroundColor Yellow
        Write-Host "  1. Install PostgreSQL for Windows" -ForegroundColor Yellow
        Write-Host "  2. Use Docker: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=yourpass postgres:15" -ForegroundColor Yellow
        Write-Host "  3. Temporarily use SQLite by setting DATABASE_URL=sqlite:///./kubera_pokisham.db" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Service status:" -ForegroundColor Cyan
Write-Host ("  Redis:        {0}" -f ($(if ($redisPortOpen) { 'Reachable' } else { 'Unavailable' }))) -ForegroundColor $(if ($redisPortOpen) { "Green" } else { "Red" })
Write-Host ("  PostgreSQL:   {0}" -f ($(if ($postgresPortOpen) { 'Reachable' } else { 'Unavailable' }))) -ForegroundColor $(if ($postgresPortOpen) { "Green" } else { "Red" })
Write-Host ""
Write-Host "Note: Redis is optional but recommended. PostgreSQL is required for full functionality." -ForegroundColor Yellow

