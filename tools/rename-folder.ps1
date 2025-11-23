# Rename Folder Script - Fix for # Character Issue
# Run this script AFTER closing Cursor/VS Code and all terminals

$ErrorActionPreference = "Stop"

$sourcePath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2"
$targetPath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Rename Folder Script" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if source exists
if (-not (Test-Path $sourcePath)) {
    Write-Host "ERROR: Source folder does not exist: $sourcePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "If you already renamed it, you're all set!" -ForegroundColor Green
    exit 1
}

# Check if target already exists
if (Test-Path $targetPath) {
    Write-Host "ERROR: Target folder already exists: $targetPath" -ForegroundColor Red
    Write-Host "Please delete or rename the existing folder first." -ForegroundColor Yellow
    exit 1
}

# Check if folder is in use
try {
    $null = [System.IO.Directory]::GetFiles($sourcePath)
} catch {
    Write-Host "WARNING: Cannot access folder - it may be in use." -ForegroundColor Yellow
    Write-Host "Make sure to:" -ForegroundColor Yellow
    Write-Host "  1. Close Cursor/VS Code completely" -ForegroundColor White
    Write-Host "  2. Close all terminals" -ForegroundColor White
    Write-Host "  3. Close file explorer windows" -ForegroundColor White
    Write-Host ""
    $response = Read-Host "Continue anyway? (y/n)"
    if ($response -ne "y" -and $response -ne "Y") {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
}

try {
    Write-Host "Renaming folder..." -ForegroundColor Yellow
    Write-Host "  From: $sourcePath" -ForegroundColor Gray
    Write-Host "  To:   $targetPath" -ForegroundColor Gray
    Write-Host ""
    
    Rename-Item -Path $sourcePath -NewName "Trading-Agent-2" -ErrorAction Stop
    
    Write-Host "SUCCESS: Folder renamed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Reopen Cursor/VS Code" -ForegroundColor White
    Write-Host "2. Open the project from: $targetPath" -ForegroundColor Cyan
    Write-Host "3. Navigate to frontend and test: cd frontend; npm run build" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "The Next.js path issue should now be resolved!" -ForegroundColor Green
    
} catch {
    Write-Host "ERROR: Failed to rename folder" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "The folder is likely in use. Please:" -ForegroundColor Yellow
    Write-Host "1. Close Cursor/VS Code completely (File -> Exit)" -ForegroundColor White
    Write-Host "2. Close all terminal windows" -ForegroundColor White
    Write-Host "3. Close any file explorer windows showing this folder" -ForegroundColor White
    Write-Host "4. Run this script again" -ForegroundColor White
    Write-Host ""
    Write-Host "OR rename manually:" -ForegroundColor Cyan
    Write-Host "   Navigate to: C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\" -ForegroundColor Gray
    Write-Host "   Right-click 'Trading Agent#2' -> Rename -> 'Trading-Agent-2'" -ForegroundColor Gray
    exit 1
}

