# Docker error audit script for JackSparrow Trading Agent
# Scans all container logs for errors and generates a comprehensive report

param(
    [int]$Hours = 24,
    [string]$OutputDir = "logs/docker-audit"
)

$ErrorActionPreference = "Stop"

# Get project root directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."

Set-Location $ProjectRoot

# Create output directory
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportFile = Join-Path $OutputDir "audit-$timestamp.md"

Write-Host "Docker Error Audit" -ForegroundColor Green
Write-Host "Scanning logs from last $Hours hours..." -ForegroundColor Yellow
Write-Host ""

# Services to audit
$services = @("backend", "agent", "frontend", "postgres", "redis")

# Error patterns
$errorPatterns = @{
    "Exception" = "Python exceptions"
    "Traceback" = "Python tracebacks"
    "ERROR" = "General errors"
    "Failed" = "Failed operations"
    "ConnectionError" = "Connection errors"
    "TimeoutError" = "Timeout errors"
    "DatabaseError" = "Database errors"
    "RedisError" = "Redis errors"
    "HTTP.*5\d{2}" = "HTTP 5xx errors"
    "HTTP.*4\d{2}" = "HTTP 4xx errors"
}

$report = @"
# Docker Error Audit Report

**Generated:** $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
**Time Range:** Last $Hours hours
**Services Audited:** $($services -join ', ')

---

"@

$totalErrors = 0

foreach ($service in $services) {
    Write-Host "Auditing $service..." -ForegroundColor Cyan
    
    # Get logs from last N hours
    $sinceTime = (Get-Date).AddHours(-$Hours).ToString("yyyy-MM-ddTHH:mm:ss")
    $logs = docker-compose logs --since $sinceTime $service 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ⚠ Could not retrieve logs for $service" -ForegroundColor Yellow
        continue
    }
    
    $serviceErrors = @{}
    
    # Scan for errors
    foreach ($pattern in $errorPatterns.Keys) {
        $matches = $logs | Select-String -Pattern $pattern -CaseSensitive:$false
        if ($matches) {
            $category = $errorPatterns[$pattern]
            if (-not $serviceErrors.ContainsKey($category)) {
                $serviceErrors[$category] = @()
            }
            foreach ($match in $matches) {
                $serviceErrors[$category] += $match.Line
            }
        }
    }
    
    # Count unique errors
    $errorCount = ($serviceErrors.Values | Measure-Object).Count
    
    if ($errorCount -gt 0) {
        $totalErrors += $errorCount
        
        $report += @"

## $service

**Total Error Categories:** $errorCount

"@
        
        foreach ($category in $serviceErrors.Keys | Sort-Object) {
            $errors = $serviceErrors[$category]
            $uniqueErrors = $errors | Select-Object -Unique
            
            $report += @"
### $category

**Occurrences:** $($errors.Count)
**Unique Errors:** $($uniqueErrors.Count)

**Sample Errors:**
``````
$($uniqueErrors | Select-Object -First 5 | Out-String)
``````

"@
        }
        
        Write-Host "  ✗ Found $errorCount error categories" -ForegroundColor Red
    } else {
        $report += @"

## $service

✓ No errors found

"@
        Write-Host "  ✓ No errors found" -ForegroundColor Green
    }
}

# Summary
$report += @"

---

## Summary

**Total Services Audited:** $($services.Count)
**Services with Errors:** $(($services | Where-Object { $serviceErrors.Count -gt 0 }).Count)
**Total Error Categories:** $totalErrors

## Recommendations

"@

if ($totalErrors -eq 0) {
    $report += @"
- ✓ No errors detected in the specified time range
- Continue monitoring for any issues
"@
} else {
    $report += @"
- Review error categories above for each service
- Check for patterns in error occurrences
- Investigate high-frequency errors first
- Consider increasing log verbosity for detailed debugging
- Review service health checks and dependencies
"@
}

# Write report
$report | Out-File -FilePath $reportFile -Encoding UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Audit Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Report saved to: $reportFile" -ForegroundColor Cyan
Write-Host "Total error categories found: $totalErrors" -ForegroundColor $(if ($totalErrors -eq 0) { "Green" } else { "Yellow" })

