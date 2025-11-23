# Docker build script for JackSparrow Trading Agent
# Builds all Docker images for the project

param(
    [string]$Version = "latest",
    [string]$CommitSha = "",
    [string]$DockerRegistry = ""
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

Write-Host "Building JackSparrow Docker images..." -ForegroundColor Green

# Get commit SHA if not provided
if (-not $CommitSha) {
    try {
        $CommitSha = (git rev-parse --short HEAD 2>$null)
        if (-not $CommitSha) {
            $CommitSha = "unknown"
        }
    } catch {
        $CommitSha = "unknown"
    }
}

$BuildDate = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")

Write-Host "Version: $Version" -ForegroundColor Yellow
Write-Host "Commit SHA: $CommitSha" -ForegroundColor Yellow
Write-Host "Build Date: $BuildDate" -ForegroundColor Yellow
Write-Host ""

# Build backend
Write-Host "Building backend image..." -ForegroundColor Green
$backendResult = docker build `
    -f backend/Dockerfile `
    -t "jacksparrow-backend:$Version" `
    -t "jacksparrow-backend:$CommitSha" `
    --build-arg BUILD_DATE="$BuildDate" `
    --build-arg VERSION="$Version" `
    --build-arg COMMIT_SHA="$CommitSha" `
    .

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Backend image built successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Backend image build failed" -ForegroundColor Red
    exit 1
}

# Build agent
Write-Host "Building agent image..." -ForegroundColor Green
$agentResult = docker build `
    -f agent/Dockerfile `
    -t "jacksparrow-agent:$Version" `
    -t "jacksparrow-agent:$CommitSha" `
    --build-arg BUILD_DATE="$BuildDate" `
    --build-arg VERSION="$Version" `
    --build-arg COMMIT_SHA="$CommitSha" `
    .

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Agent image built successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Agent image build failed" -ForegroundColor Red
    exit 1
}

# Build frontend
Write-Host "Building frontend image..." -ForegroundColor Green
$frontendResult = docker build `
    -f frontend/Dockerfile `
    -t "jacksparrow-frontend:$Version" `
    -t "jacksparrow-frontend:$CommitSha" `
    --build-arg BUILD_DATE="$BuildDate" `
    --build-arg VERSION="$Version" `
    --build-arg COMMIT_SHA="$CommitSha" `
    frontend/

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Frontend image built successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Frontend image build failed" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "All images built successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Images:"
docker images | Select-String "jacksparrow" | Select-Object -First 3

# Optional: Push to registry if DOCKER_REGISTRY is set
if ($DockerRegistry) {
    Write-Host ""
    Write-Host "Pushing images to registry: $DockerRegistry" -ForegroundColor Yellow
    
    docker tag "jacksparrow-backend:$Version" "${DockerRegistry}/jacksparrow-backend:$Version"
    docker tag "jacksparrow-agent:$Version" "${DockerRegistry}/jacksparrow-agent:$Version"
    docker tag "jacksparrow-frontend:$Version" "${DockerRegistry}/jacksparrow-frontend:$Version"
    
    docker push "${DockerRegistry}/jacksparrow-backend:$Version"
    docker push "${DockerRegistry}/jacksparrow-agent:$Version"
    docker push "${DockerRegistry}/jacksparrow-frontend:$Version"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Images pushed to registry" -ForegroundColor Green
    } else {
        Write-Host "✗ Failed to push images to registry" -ForegroundColor Red
        exit 1
    }
}

