# Production Docker deployment script for JackSparrow Trading Agent
# Rebuilds all images from scratch and deploys the stack
# PowerShell version for Windows

param(
    [switch]$RemoveImages,
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"

# Colors for output (PowerShell)
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Color
}

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

Set-Location $ProjectRoot

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-ColorOutput "Error: .env file not found" "Red"
    Write-ColorOutput "Please create .env file from .env.example" "Yellow"
    exit 1
}

Write-ColorOutput "========================================" "Green"
Write-ColorOutput "JackSparrow Production Deployment" "Green"
Write-ColorOutput "========================================" "Green"
Write-Host ""

# Function to check service health
function Check-ServiceHealth {
    param(
        [string]$Service,
        [int]$MaxAttempts = 30
    )
    
    Write-ColorOutput "Waiting for $Service to be healthy..." "Blue"
    $attempt = 1
    
    while ($attempt -le $MaxAttempts) {
        $status = docker compose ps $Service 2>&1 | Select-String "healthy"
        if ($status) {
            Write-ColorOutput "[OK] $Service is healthy" "Green"
            return $true
        }
        
        $unhealthy = docker compose ps $Service 2>&1 | Select-String "unhealthy"
        if ($unhealthy) {
            Write-ColorOutput "[FAIL] $Service is unhealthy" "Red"
            docker compose logs --tail=50 $Service
            return $false
        }
        
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
        $attempt++
    }
    
    Write-Host ""
    Write-ColorOutput "[TIMEOUT] $Service health check timeout" "Red"
    docker compose logs --tail=50 $Service
    return $false
}

# Step 1: Stop existing containers
Write-ColorOutput "Step 1: Stopping existing containers..." "Yellow"
docker compose down 2>&1 | Out-Null
Write-ColorOutput "[OK] Containers stopped" "Green"
Write-Host ""

# Step 2: Remove old images if requested
if ($RemoveImages) {
    Write-ColorOutput "Step 2: Removing old images..." "Yellow"
    $images = docker images --format "{{.ID}}" --filter "reference=jacksparrow*"
    if ($images) {
        $images | ForEach-Object { docker rmi -f $_ 2>&1 | Out-Null }
    }
    Write-ColorOutput "[OK] Old images removed" "Green"
    Write-Host ""
}

# Step 3: Remove volumes if requested (WARNING: This deletes data!)
if ($RemoveVolumes) {
    Write-ColorOutput "Step 3: Removing volumes (WARNING: This deletes database data!)..." "Yellow"
    $confirm = Read-Host "Are you sure you want to delete all volumes? (yes/no)"
        if ($confirm -eq "yes") {
        docker compose down -v 2>&1 | Out-Null
        Write-ColorOutput "[OK] Volumes removed" "Green"
    } else {
        Write-ColorOutput "Volumes removal cancelled" "Yellow"
    }
    Write-Host ""
}

# Step 4: Rebuild all images with --no-cache
Write-ColorOutput "Step 4: Rebuilding all images from scratch (--no-cache)..." "Yellow"
Write-ColorOutput "This may take several minutes..." "Blue"
Write-Host ""

# Build backend
Write-ColorOutput "Building backend image..." "Blue"
docker compose build --no-cache backend
if ($LASTEXITCODE -eq 0) {
    Write-ColorOutput "[OK] Backend image built successfully" "Green"
} else {
    Write-ColorOutput "[FAIL] Backend image build failed" "Red"
    exit 1
}
Write-Host ""

# Build agent
Write-ColorOutput "Building agent image..." "Blue"
docker compose build --no-cache agent
if ($LASTEXITCODE -eq 0) {
    Write-ColorOutput "[OK] Agent image built successfully" "Green"
} else {
    Write-ColorOutput "[FAIL] Agent image build failed" "Red"
    exit 1
}
Write-Host ""

# Build frontend
Write-ColorOutput "Building frontend image..." "Blue"
docker compose build --no-cache frontend
if ($LASTEXITCODE -eq 0) {
    Write-ColorOutput "[OK] Frontend image built successfully" "Green"
} else {
    Write-ColorOutput "[FAIL] Frontend image build failed" "Red"
    exit 1
}
Write-Host ""

# Step 5: Start all services
Write-ColorOutput "Step 5: Starting all services..." "Yellow"
docker compose up -d

Write-Host ""
Write-ColorOutput "Waiting for services to initialize..." "Blue"
Start-Sleep -Seconds 15

# Step 6: Check health of all services
Write-Host ""
Write-ColorOutput "Step 6: Checking service health..." "Yellow"

# Check database services first
$null = Check-ServiceHealth "postgres" 20
$null = Check-ServiceHealth "redis" 15

# Check application services
$null = Check-ServiceHealth "backend" 30
$null = Check-ServiceHealth "agent" 40
$null = Check-ServiceHealth "frontend" 30

# Step 7: Display service status
Write-Host ""
Write-ColorOutput "========================================" "Green"
Write-ColorOutput "Deployment Summary" "Green"
Write-ColorOutput "========================================" "Green"
Write-Host ""
docker compose ps
Write-Host ""

# Step 8: Display service URLs
Write-ColorOutput "Service URLs:" "Green"
$frontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "3000" }
$backendPort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
$agentPort = if ($env:FEATURE_SERVER_PORT) { $env:FEATURE_SERVER_PORT } else { "8001" }

Write-Host "  Frontend:    http://localhost:$frontendPort"
Write-Host "  Backend API: http://localhost:$backendPort"
Write-Host "  API Docs:    http://localhost:$backendPort/docs"
Write-Host "  Agent:       http://localhost:$agentPort"
Write-Host ""

# Step 9: Display logs command
Write-ColorOutput "To view logs, run:" "Blue"
Write-Host "  docker compose logs -f [service_name]"
Write-Host ""
Write-ColorOutput "To view all logs:" "Blue"
Write-Host "  docker compose logs -f"
Write-Host ""

Write-ColorOutput "========================================" "Green"
Write-ColorOutput "Production deployment completed!" "Green"
Write-ColorOutput "========================================" "Green"

