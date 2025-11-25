# Fix Path Issue Script
# This script creates a junction point to work around the # character in the folder name
# Usage: Run this script from an elevated PowerShell prompt

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = $projectRoot
$targetPath = $projectRoot -replace "#", "-"

Write-Host "This helper explains how to resolve the Next.js path issue caused by the # character."
Write-Host ""

if ($projectRoot -notmatch "#") {
    Write-Host "Good news! Your current path does not include a # character:" -ForegroundColor Green
    Write-Host "  $projectRoot" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "No action is required." -ForegroundColor Green
    exit 0
}

Write-Host "RECOMMENDED SOLUTION: Rename the folder"
Write-Host "1. Close all applications using files in the project"
Write-Host "2. Rename '$sourcePath' to '$targetPath'"
Write-Host "3. Update any scripts or shortcuts that reference the old path"
Write-Host ""
Write-Host "ALTERNATIVE (if renaming isn't possible):"
Write-Host "You can create a symlink, but this may cause other issues."
Write-Host ""
Write-Host "Current path: $sourcePath"
Write-Host "Suggested new name: $targetPath"

