# Docker container start script for JackSparrow Trading Agent
# Starts individual containers with dependency handling

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string[]]$Containers
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Service dependencies mapping
$dependencies = @{
    "backend" = @("postgres", "redis")
    "agent" = @("postgres", "redis", "backend")
    "frontend" = @("backend")
    "postgres" = @()
    "redis" = @()
}

# Function to check if container is running
function Test-ContainerRunning {
    param([string]$Service)
    
    $status = docker-compose ps $Service 2>$null | Select-String -Pattern "Up|running"
    return $null -ne $status
}

# Function to start container
function Start-Container {
    param([string]$Service)
    
    if (Test-ContainerRunning $Service) {
        Write-Host "✓ $Service is already running" -ForegroundColor Green
        return $true
    }
    
    Write-Host "Starting $Service..." -ForegroundColor Blue
    
    # Start dependencies first
    if ($dependencies.ContainsKey($Service)) {
        foreach ($dep in $dependencies[$Service]) {
            if (-not (Test-ContainerRunning $dep)) {
                Write-Host "  Starting dependency: $dep" -ForegroundColor Yellow
                Start-Container $dep | Out-Null
            }
        }
    }
    
    # Start the container
    docker-compose up -d $Service
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ $Service started successfully" -ForegroundColor Green
        
        # Wait for health check
        Write-Host "  Waiting for $Service to be healthy..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
        
        $maxAttempts = 30
        $attempt = 1
        while ($attempt -le $maxAttempts) {
            $status = docker-compose ps $Service 2>$null | Select-String -Pattern "healthy"
            if ($null -ne $status) {
                Write-Host "✓ $Service is healthy" -ForegroundColor Green
                return $true
            }
            Start-Sleep -Seconds 2
            $attempt++
        }
        
        Write-Host "⚠ $Service started but health check pending" -ForegroundColor Yellow
        return $true
    } else {
        Write-Host "✗ Failed to start $Service" -ForegroundColor Red
        return $false
    }
}

Write-Host "Starting Docker Containers" -ForegroundColor Green
Write-Host "Containers: $($Containers -join ', ')" -ForegroundColor Yellow
Write-Host ""

$success = $true
foreach ($container in $Containers) {
    if (-not (Start-Container $container)) {
        $success = $false
    }
}

Write-Host ""
if ($success) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "All containers started successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    docker-compose ps
} else {
    Write-Host "Some containers failed to start" -ForegroundColor Red
    exit 1
}

