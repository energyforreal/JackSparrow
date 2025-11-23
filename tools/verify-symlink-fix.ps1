# Verification Script - Test Next.js Fix After Symlink Creation
# Run this script after creating the symlink and switching to the symlink path

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Verify Symlink Fix" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the symlink path
$currentPath = Get-Location
$expectedSymlinkPath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2"

if ($currentPath.Path -notlike "*Trading-Agent-2*" -and $currentPath.Path -like "*Trading Agent#2*") {
    Write-Host "WARNING: You're still in the old path with # character!" -ForegroundColor Yellow
    Write-Host "Current path: $($currentPath.Path)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Please switch to the symlink path:" -ForegroundColor Yellow
    Write-Host "  cd `"$expectedSymlinkPath`"" -ForegroundColor Cyan
    Write-Host ""
    $response = Read-Host "Continue anyway? (y/n)"
    if ($response -ne "y" -and $response -ne "Y") {
        exit 1
    }
}

# Check if frontend directory exists
$frontendPath = Join-Path $currentPath.Path "frontend"
if (-not (Test-Path $frontendPath)) {
    Write-Host "ERROR: frontend directory not found!" -ForegroundColor Red
    Write-Host "Make sure you're in the project root directory." -ForegroundColor Yellow
    exit 1
}

Write-Host "Step 1: Checking current path..." -ForegroundColor Yellow
Write-Host "Current path: $($currentPath.Path)" -ForegroundColor Gray

# Check if symlink exists
$symlinkPath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2"
if (Test-Path $symlinkPath) {
    $linkInfo = Get-Item $symlinkPath
    if ($linkInfo.LinkType -eq "SymbolicLink") {
        Write-Host "✓ Symlink exists and is valid" -ForegroundColor Green
        Write-Host "  Target: $($linkInfo.Target)" -ForegroundColor Gray
    } else {
        Write-Host "⚠ Path exists but is not a symlink" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠ Symlink path does not exist yet" -ForegroundColor Yellow
    Write-Host "  Run: .\tools\create-symlink.ps1 (as Administrator)" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Step 2: Clearing Next.js build cache..." -ForegroundColor Yellow
Push-Location $frontendPath

$nextPath = Join-Path $frontendPath ".next"
if (Test-Path $nextPath) {
    Remove-Item -Recurse -Force $nextPath
    Write-Host "✓ Cleared .next directory" -ForegroundColor Green
} else {
    Write-Host "✓ No .next directory to clear" -ForegroundColor Green
}

Write-Host ""
Write-Host "Step 3: Testing Next.js build..." -ForegroundColor Yellow
Write-Host "This may take a minute..." -ForegroundColor Gray
Write-Host ""

# Check if node_modules exists
if (-not (Test-Path "node_modules")) {
    Write-Host "WARNING: node_modules not found. Installing dependencies..." -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: npm install failed" -ForegroundColor Red
        Pop-Location
        exit 1
    }
}

# Run the build
Write-Host "Running: npm run build" -ForegroundColor Cyan
Write-Host ""

try {
    npm run build
    $buildSuccess = $LASTEXITCODE -eq 0
    
    Write-Host ""
    if ($buildSuccess) {
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  SUCCESS!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "✓ Next.js build completed successfully" -ForegroundColor Green
        Write-Host "✓ The symlink fix is working!" -ForegroundColor Green
        Write-Host ""
        Write-Host "The 'app-router.js#' error should be resolved." -ForegroundColor White
        Write-Host "You can now run 'npm run dev' to start the development server." -ForegroundColor White
    } else {
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "  BUILD FAILED" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "The build still has errors. Check the output above." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Common issues:" -ForegroundColor Yellow
        Write-Host "1. Make sure you're using the symlink path (Trading-Agent-2)" -ForegroundColor White
        Write-Host "2. Make sure Cursor/VS Code is opened from the symlink path" -ForegroundColor White
        Write-Host "3. Check if there are any other errors in the build output" -ForegroundColor White
        Pop-Location
        exit 1
    }
} catch {
    Write-Host "ERROR: Build failed with exception" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Pop-Location
    exit 1
}

Pop-Location

Write-Host ""
Write-Host "Verification complete!" -ForegroundColor Green

