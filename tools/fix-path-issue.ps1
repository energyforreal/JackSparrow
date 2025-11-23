# Fix Path Issue Script
# This script creates a junction point to work around the # character in the folder name
# Usage: Run this script from an elevated PowerShell prompt

$sourcePath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2"
$targetPath = "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2"

Write-Host "This script will help you resolve the Next.js path issue caused by the # character."
Write-Host ""
Write-Host "RECOMMENDED SOLUTION: Rename the folder"
Write-Host "1. Close all applications using files in the project"
Write-Host "2. Rename 'Trading Agent#2' to 'Trading-Agent-2' or 'Trading Agent 2'"
Write-Host "3. Update any scripts or shortcuts that reference the old path"
Write-Host ""
Write-Host "ALTERNATIVE (if renaming isn't possible):"
Write-Host "You can create a symlink, but this may cause other issues."
Write-Host ""
Write-Host "Current path: $sourcePath"
Write-Host "Suggested new name: Trading-Agent-2"

