# Docker development startup script for JackSparrow Trading Agent
# Starts development environment with hot-reload enabled

param(
    [switch]$Build,
    [switch]$Detached,
    [string]$Service = ""
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Check if .env file exists
if (-not (Test-Path .env)) {
    Write-Host "Warning: .env file not found" -ForegroundColor Yellow
    Write-Host "Using default environment variables" -ForegroundColor Yellow
}

Write-Host "JackSparrow Docker Development Environment" -ForegroundColor Green
Write-Host "Hot-reload enabled - code changes will be reflected automatically" -ForegroundColor Cyan
Write-Host ""

# Build images if requested
if ($Build) {
    Write-Host "Building development images..." -ForegroundColor Blue
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml build
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed" -ForegroundColor Red
        exit 1
    }
    Write-Host ""
}

# Start services
$composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")

if ($Detached) {
    $composeArgs += "up", "-d"
    Write-Host "Starting services in detached mode..." -ForegroundColor Blue
} else {
    $composeArgs += "up"
    Write-Host "Starting services (press Ctrl+C to stop)..." -ForegroundColor Blue
}

if ($Service) {
    $composeArgs += $Service
    Write-Host "Starting service: $Service" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Services will auto-reload on code changes:" -ForegroundColor Cyan
Write-Host "  - Backend: uvicorn --reload" -ForegroundColor White
Write-Host "  - Frontend: npm run dev (Next.js hot-reload)" -ForegroundColor White
Write-Host "  - Agent: Python module reload" -ForegroundColor White
Write-Host ""

docker-compose $composeArgs

