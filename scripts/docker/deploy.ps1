# Docker deployment script for JackSparrow Trading Agent
# Deploys the application using docker-compose

param(
    [Parameter(Position=0)]
    [ValidateSet("up", "down", "restart", "update", "logs")]
    [string]$Mode = "up",
    
    [switch]$PullImages
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Check if .env file exists
if (-not (Test-Path .env)) {
    Write-Host "Error: .env file not found" -ForegroundColor Red
    Write-Host "Please create .env file from .env.example" -ForegroundColor Yellow
    exit 1
}

# Function to check service health
function Check-Health {
    param(
        [string]$Service,
        [int]$MaxAttempts = 30
    )
    
    Write-Host "Waiting for $Service to be healthy..." -ForegroundColor Blue
    $attempt = 1
    
    while ($attempt -le $MaxAttempts) {
        $status = docker-compose ps $Service 2>$null | Select-String -Pattern "healthy|unhealthy"
        
        if ($status -match "healthy") {
            Write-Host "[OK] $Service is healthy" -ForegroundColor Green
            return $true
        }
        
        if ($status -match "unhealthy") {
            Write-Host "[FAIL] $Service is unhealthy" -ForegroundColor Red
            return $false
        }
        
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
        $attempt++
    }
    
    Write-Host ""
    Write-Host "[FAIL] $Service health check timeout" -ForegroundColor Red
    return $false
}

Write-Host "JackSparrow Docker Deployment" -ForegroundColor Green
Write-Host "Mode: $Mode" -ForegroundColor Yellow
Write-Host ""

# Pull latest images if requested
if ($PullImages) {
    Write-Host "Pulling latest images..." -ForegroundColor Blue
    docker-compose pull
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Some images may not be available in registry" -ForegroundColor Yellow
    }
    Write-Host ""
}

switch ($Mode) {
    "up" {
        Write-Host "Starting all services..." -ForegroundColor Green
        docker-compose up -d --build
        
        Write-Host ""
        Write-Host "Waiting for services to start..." -ForegroundColor Blue
        Start-Sleep -Seconds 10
        
        # Check health of critical services
        Check-Health "postgres" 15 | Out-Null
        Check-Health "redis" 10 | Out-Null
        Check-Health "backend" 20 | Out-Null
        Check-Health "agent" 30 | Out-Null
        Check-Health "frontend" 20 | Out-Null
        
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "Deployment completed!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        docker-compose ps
    }
    
    "down" {
        Write-Host "Stopping all services..." -ForegroundColor Yellow
        docker-compose down
        Write-Host "[OK] All services stopped" -ForegroundColor Green
    }
    
    "restart" {
        Write-Host "Restarting all services..." -ForegroundColor Yellow
        docker-compose restart
        Write-Host "[OK] All services restarted" -ForegroundColor Green
    }
    
    "update" {
        Write-Host "Performing rolling update..." -ForegroundColor Blue
        
        # Pull latest images
        docker-compose pull
        
        # Update services one by one
        Write-Host "Updating backend..." -ForegroundColor Blue
        docker-compose up -d --no-deps backend
        Check-Health "backend" 20 | Out-Null
        
        Write-Host "Updating agent..." -ForegroundColor Blue
        docker-compose up -d --no-deps agent
        Check-Health "agent" 30 | Out-Null
        
        Write-Host "Updating frontend..." -ForegroundColor Blue
        docker-compose up -d --no-deps frontend
        Check-Health "frontend" 20 | Out-Null
        
        Write-Host "[OK] Rolling update completed" -ForegroundColor Green
    }
    
    "logs" {
        docker-compose logs -f
    }
    
    default {
        Write-Host "Unknown mode: $Mode" -ForegroundColor Red
        Write-Host "Usage: .\deploy.ps1 [up|down|restart|update|logs] [-PullImages]"
        exit 1
    }
}

