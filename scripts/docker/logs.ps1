# Docker logs analysis script for JackSparrow Trading Agent
# Analyzes Docker container logs with filtering and export capabilities

param(
    [Parameter(Position=0)]
    [string]$Service = "",
    
    [ValidateSet("ERROR", "WARNING", "INFO", "DEBUG", "ALL")]
    [string]$Level = "ALL",
    
    [int]$Tail = 100,
    
    [switch]$Follow,
    
    [switch]$Export,
    
    [string]$OutputDir = "logs/docker-logs"
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Color functions
function Write-ColorLog {
    param([string]$Line, [string]$Service)
    
    $colors = @{
        "backend" = "Cyan"
        "agent" = "Green"
        "frontend" = "Yellow"
        "postgres" = "Blue"
        "redis" = "Red"
    }
    
    $color = if ($colors.ContainsKey($Service)) { $colors[$Service] } else { "White" }
    
    if ($Line -match "ERROR|Exception|Traceback|Failed|Error") {
        Write-Host $Line -ForegroundColor Red
    } elseif ($Line -match "WARNING|Warning") {
        Write-Host $Line -ForegroundColor Yellow
    } elseif ($Line -match "INFO|info") {
        Write-Host $Line -ForegroundColor Green
    } else {
        Write-Host $Line -ForegroundColor $color
    }
}

# Create output directory if exporting
if ($Export) {
    if (-not (Test-Path $OutputDir)) {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $outputFile = Join-Path $OutputDir "logs-$Service-$Level-$timestamp.log"
}

Write-Host "Docker Logs Analysis" -ForegroundColor Green
Write-Host "Service: $Service" -ForegroundColor Yellow
Write-Host "Level: $Level" -ForegroundColor Yellow
Write-Host "Tail: $Tail" -ForegroundColor Yellow
if ($Export) {
    Write-Host "Exporting to: $outputFile" -ForegroundColor Cyan
}
Write-Host ""

# Get list of services
$services = @("backend", "agent", "frontend", "postgres", "redis")
if ($Service) {
    $services = @($Service)
}

$logContent = @()

foreach ($svc in $services) {
    Write-Host "=== $svc ===" -ForegroundColor Cyan
    
    $logs = docker-compose logs --tail=$Tail $svc 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        $filteredLogs = $logs | Where-Object {
            if ($Level -eq "ALL") { $true }
            elseif ($Level -eq "ERROR") { $_ -match "ERROR|Exception|Traceback|Failed|Error" }
            elseif ($Level -eq "WARNING") { $_ -match "WARNING|Warning" }
            elseif ($Level -eq "INFO") { $_ -match "INFO|info" }
            elseif ($Level -eq "DEBUG") { $_ -match "DEBUG|debug" }
            else { $true }
        }
        
        foreach ($line in $filteredLogs) {
            Write-ColorLog -Line $line -Service $svc
            if ($Export) {
                $logContent += "[$svc] $line"
            }
        }
    } else {
        Write-Host "Failed to get logs for $svc" -ForegroundColor Red
    }
    
    Write-Host ""
}

# Export logs if requested
if ($Export -and $logContent.Count -gt 0) {
    $logContent | Out-File -FilePath $outputFile -Encoding UTF8
    Write-Host "Logs exported to: $outputFile" -ForegroundColor Green
}

# Follow mode
if ($Follow) {
    Write-Host "Following logs (press Ctrl+C to stop)..." -ForegroundColor Cyan
    if ($Service) {
        docker-compose logs -f $Service
    } else {
        docker-compose logs -f
    }
}

