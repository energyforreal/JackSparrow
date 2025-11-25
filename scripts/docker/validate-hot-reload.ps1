# Validation script for Docker hot reload setup (PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "Validating Docker Hot Reload Setup..." -ForegroundColor Blue
Write-Host ""

# Check if docker-compose files exist
Write-Host "Checking Docker Compose files..." -ForegroundColor Blue
if (-not (Test-Path "docker-compose.yml")) {
    Write-Host "✗ docker-compose.yml not found" -ForegroundColor Red
    exit 1
}
Write-Host "✓ docker-compose.yml found" -ForegroundColor Green

if (-not (Test-Path "docker-compose.dev.yml")) {
    Write-Host "✗ docker-compose.dev.yml not found" -ForegroundColor Red
    exit 1
}
Write-Host "✓ docker-compose.dev.yml found" -ForegroundColor Green

# Check if Dockerfile.dev files exist
Write-Host ""
Write-Host "Checking development Dockerfiles..." -ForegroundColor Blue
$services = @("backend", "agent", "frontend")
foreach ($service in $services) {
    if ($service -eq "frontend") {
        $dockerfile = "frontend/Dockerfile.dev"
    } else {
        $dockerfile = "$service/Dockerfile.dev"
    }
    
    if (-not (Test-Path $dockerfile)) {
        Write-Host "✗ $dockerfile not found" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ $dockerfile found" -ForegroundColor Green
}

# Check if dev_watcher.py exists
Write-Host ""
Write-Host "Checking agent file watcher..." -ForegroundColor Blue
if (-not (Test-Path "agent/scripts/dev_watcher.py")) {
    Write-Host "✗ agent/scripts/dev_watcher.py not found" -ForegroundColor Red
    exit 1
}
Write-Host "✓ agent/scripts/dev_watcher.py found" -ForegroundColor Green

# Check if watchdog is mentioned in Dockerfile.dev
Write-Host ""
Write-Host "Checking watchdog installation..." -ForegroundColor Blue
$dockerfileContent = Get-Content "agent/Dockerfile.dev" -Raw
if ($dockerfileContent -match "watchdog") {
    Write-Host "✓ watchdog installation found in agent/Dockerfile.dev" -ForegroundColor Green
} else {
    Write-Host "⚠ watchdog not found in agent/Dockerfile.dev" -ForegroundColor Yellow
}

if ($dockerfileContent -match "dev_watcher") {
    Write-Host "✓ dev_watcher CMD found in agent/Dockerfile.dev" -ForegroundColor Green
} else {
    Write-Host "⚠ dev_watcher CMD not found in agent/Dockerfile.dev" -ForegroundColor Yellow
}

# Check volume mounts in docker-compose.dev.yml
Write-Host ""
Write-Host "Checking volume mounts..." -ForegroundColor Blue
$devComposeContent = Get-Content "docker-compose.dev.yml" -Raw
if ($devComposeContent -match "./backend:/app/backend") {
    Write-Host "✓ Backend volume mount found" -ForegroundColor Green
} else {
    Write-Host "⚠ Backend volume mount not found" -ForegroundColor Yellow
}

if ($devComposeContent -match "./agent:/app/agent") {
    Write-Host "✓ Agent volume mount found" -ForegroundColor Green
} else {
    Write-Host "⚠ Agent volume mount not found" -ForegroundColor Yellow
}

if ($devComposeContent -match "./frontend:/app") {
    Write-Host "✓ Frontend volume mount found" -ForegroundColor Green
} else {
    Write-Host "⚠ Frontend volume mount not found" -ForegroundColor Yellow
}

# Check if uvicorn --reload is used
Write-Host ""
Write-Host "Checking backend reload configuration..." -ForegroundColor Blue
$backendDockerfileContent = Get-Content "backend/Dockerfile.dev" -Raw
if ($devComposeContent -match "--reload" -or $backendDockerfileContent -match "--reload") {
    Write-Host "✓ Backend reload flag found" -ForegroundColor Green
} else {
    Write-Host "⚠ Backend reload flag not found" -ForegroundColor Yellow
}

# Check if frontend uses npm run dev
Write-Host ""
Write-Host "Checking frontend dev server..." -ForegroundColor Blue
$frontendDockerfileContent = Get-Content "frontend/Dockerfile.dev" -Raw
if ($frontendDockerfileContent -match "npm run dev") {
    Write-Host "✓ Frontend dev server configuration found" -ForegroundColor Green
} else {
    Write-Host "⚠ Frontend dev server configuration not found" -ForegroundColor Yellow
}

# Check documentation
Write-Host ""
Write-Host "Checking documentation..." -ForegroundColor Blue
if (Test-Path "docs/docker-hot-reload.md") {
    Write-Host "✓ docs/docker-hot-reload.md found" -ForegroundColor Green
} else {
    Write-Host "⚠ docs/docker-hot-reload.md not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Validation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To test hot reload:" -ForegroundColor Blue
Write-Host "1. Start services: .\scripts\docker\dev-start.ps1 -Build" -ForegroundColor Yellow
Write-Host "2. Make a change to a Python file in backend/ or agent/" -ForegroundColor White
Write-Host "3. Check logs: docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f" -ForegroundColor Yellow

