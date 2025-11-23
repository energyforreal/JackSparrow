# Create Symlink Workaround for # Character in Folder Name
# Run this script from PowerShell as Administrator
# This creates a symlink without the # character that you can use instead

$ErrorActionPreference = "Stop"

$sourcePath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2"
$linkPath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2"

Write-Host "Creating symlink to work around # character issue..." -ForegroundColor Yellow
Write-Host ""

# Check if source exists
if (-not (Test-Path $sourcePath)) {
    Write-Host "ERROR: Source path does not exist: $sourcePath" -ForegroundColor Red
    exit 1
}

# Check if link already exists
if (Test-Path $linkPath) {
    Write-Host "WARNING: Link path already exists: $linkPath" -ForegroundColor Yellow
    $response = Read-Host "Do you want to remove it and create a new symlink? (y/n)"
    if ($response -eq "y" -or $response -eq "Y") {
        Remove-Item $linkPath -Force -Recurse
    } else {
        Write-Host "Aborted." -ForegroundColor Red
        exit 1
    }
}

try {
    # Create the symlink
    New-Item -ItemType SymbolicLink -Path $linkPath -Target $sourcePath -Force
    
    Write-Host "SUCCESS: Symlink created!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Source: $sourcePath" -ForegroundColor Cyan
    Write-Host "Link:   $linkPath" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Close all applications using the old path (if not already closed)" -ForegroundColor White
    Write-Host "2. Reopen Cursor/VS Code and open the project from:" -ForegroundColor White
    Write-Host "   $linkPath" -ForegroundColor Cyan
    Write-Host "3. Verify the fix by running:" -ForegroundColor White
    Write-Host "   .\tools\verify-symlink-fix.ps1" -ForegroundColor Cyan
    Write-Host "4. Or test manually:" -ForegroundColor White
    Write-Host "   cd frontend" -ForegroundColor Cyan
    Write-Host "   npm run build" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Note: The symlink allows you to access the project without the # character in the path." -ForegroundColor Gray
    Write-Host "Always use the symlink path ($linkPath) for development from now on." -ForegroundColor Gray
    
} catch {
    Write-Host "ERROR: Failed to create symlink" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Make sure you're running PowerShell as Administrator!" -ForegroundColor Yellow
    exit 1
}

