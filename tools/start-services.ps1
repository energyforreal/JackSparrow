# Start required services for JackSparrow Trading Agent
# This script helps start PostgreSQL and Redis on Windows

Write-Host "Starting required services for JackSparrow Trading Agent..." -ForegroundColor Cyan
Write-Host ""

# Check if Redis is already running
$redisRunning = Get-Process -Name "redis-server" -ErrorAction SilentlyContinue
if ($redisRunning) {
    Write-Host "✓ Redis is already running" -ForegroundColor Green
} else {
    Write-Host "Starting Redis server..." -ForegroundColor Yellow
    $redisPath = Join-Path $PSScriptRoot "..\redis-tmp\redis-server.exe"
    $redisConfig = Join-Path $PSScriptRoot "..\redis-tmp\redis.windows.conf"
    
    if (Test-Path $redisPath) {
        Start-Process -FilePath $redisPath -ArgumentList $redisConfig -WindowStyle Minimized
        Start-Sleep -Seconds 2
        Write-Host "✓ Redis server started" -ForegroundColor Green
    } else {
        Write-Host "✗ Redis executable not found at: $redisPath" -ForegroundColor Red
        Write-Host "  Please install Redis or use Docker: docker run -d -p 6379:6379 redis:7.2-alpine" -ForegroundColor Yellow
    }
}

Write-Host ""

# Check if PostgreSQL is running
$postgresRunning = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Running' }
if ($postgresRunning) {
    Write-Host "✓ PostgreSQL service is already running" -ForegroundColor Green
} else {
    Write-Host "Attempting to start PostgreSQL service..." -ForegroundColor Yellow
    
    # Try to find and start PostgreSQL service
    $postgresServices = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($postgresServices) {
        $service = $postgresServices | Select-Object -First 1
        try {
            Start-Service -Name $service.Name
            Write-Host "✓ PostgreSQL service started: $($service.Name)" -ForegroundColor Green
        } catch {
            Write-Host "✗ Failed to start PostgreSQL service: $_" -ForegroundColor Red
            Write-Host "  Please start it manually via Services app or use:" -ForegroundColor Yellow
            Write-Host "  net start $($service.Name)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "✗ PostgreSQL service not found" -ForegroundColor Red
        Write-Host "  Options:" -ForegroundColor Yellow
        Write-Host "  1. Install PostgreSQL for Windows" -ForegroundColor Yellow
        Write-Host "  2. Use Docker: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=yourpass postgres:15" -ForegroundColor Yellow
        Write-Host "  3. Use SQLite by setting DATABASE_URL=sqlite:///./kubera_pokisham.db in .env" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Service status:" -ForegroundColor Cyan
Write-Host "  Redis: $($(Get-Process -Name "redis-server" -ErrorAction SilentlyContinue) ? 'Running' : 'Not Running')" -ForegroundColor $(if (Get-Process -Name "redis-server" -ErrorAction SilentlyContinue) { "Green" } else { "Red" })
$pgStatus = (Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Running' } | Measure-Object).Count
Write-Host "  PostgreSQL: $(if ($pgStatus -gt 0) { 'Running' } else { 'Not Running' })" -ForegroundColor $(if ($pgStatus -gt 0) { "Green" } else { "Red" })
Write-Host ""
Write-Host "Note: Redis is optional but recommended. PostgreSQL is required for full functionality." -ForegroundColor Yellow

