# Symlink Setup Guide - Fix for Next.js Path Issue

## Problem Overview

The `#` character in folder names such as "Trading Agent#2" causes Next.js to incorrectly parse module paths. When Next.js tries to resolve `app-router.js`, it looks for `app-router.js#` instead, causing build failures. Newer checkouts already use `Trading Agent 2` (no `#`), so you may not need this guide—the scripts will detect that and exit cleanly.

## Solution

Create a symbolic link (symlink) that provides a path without the `#` character. The symlink points to your original folder, so all your files stay in place - Next.js just accesses them via a cleaner path.

## Step-by-Step Instructions

### Step 1: Close Applications

Before creating the symlink, close all applications using the project:

1. **Close Cursor/VS Code completely** (File → Exit, don't just close the window)
2. **Close all terminal windows** that might have the project directory open
3. **Close any file explorers** showing the project folder

### Step 2: Open PowerShell as Administrator

1. Press `Windows Key` to open Start menu
2. Type `PowerShell`
3. **Right-click** on "Windows PowerShell" or "PowerShell"
4. Select **"Run as Administrator"**
5. Click "Yes" if prompted by User Account Control

### Step 3: Navigate to Project Root

In the Administrator PowerShell window, navigate to your project (adjust the path if yours is different):

```powershell
cd "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent 2"
```

### Step 4: Run the Symlink Creation Script

Execute the script (it auto-detects whether the `#` workaround is required):

```powershell
.\tools\create-symlink.ps1
```

The script will:
- Verify the source folder exists
- Check if the symlink already exists (and ask if you want to recreate it)
- Create the symlink at: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2`
- Provide next steps

**Expected Output:**
```
SUCCESS: Symlink created!

Source: C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2
Link:   C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2
```

### Step 5: Switch to Symlink Path

1. **Open Cursor/VS Code** (as normal, not as Administrator)
2. **Open folder**: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2`
3. All your files will be accessible - the symlink is transparent

### Step 6: Verify the Fix

1. Open a terminal in Cursor (or PowerShell/Command Prompt)
2. Navigate to the frontend directory:
   ```powershell
   cd frontend
   ```
3. Clear the Next.js build cache:
   ```powershell
   if (Test-Path .next) { Remove-Item -Recurse -Force .next }
   ```
4. Test the build:
   ```powershell
   npm run build
   ```
5. If the build succeeds without errors, the fix worked!

## Troubleshooting

### Error: "Cannot access the file because it is being used by another process"

**Solution**: Make sure you've closed:
- Cursor/VS Code completely
- All terminal windows
- File explorer windows
- Any running Node.js processes (check Task Manager)

### Error: "You do not have sufficient privileges"

**Solution**: You must run PowerShell as Administrator. Right-click PowerShell and select "Run as Administrator".

### Error: "Link path already exists"

**Solution**: The script will ask if you want to remove the existing symlink. Type `y` and press Enter to recreate it.

### Build Still Fails

**Solution**: 
1. Make sure you're using the symlink path (check your current directory: `pwd` or `Get-Location`)
2. Clear the `.next` directory: `Remove-Item -Recurse -Force frontend\.next`
3. Try the build again

## What Changed?

- **Original folder**: `Trading Agent#2` - stays exactly as it is (only applicable to legacy setups)
- **Symlink created**: `Trading-Agent-2` - points to the original folder
- **Next.js now uses**: The symlink path (without `#`), resolving the path issue

## Important Notes

- **Always use the symlink path** (`Trading-Agent-2`) for development from now on
- The original folder still exists and contains all your files
- Both paths access the same files (symlink is transparent)
- Git will work normally from either path (it resolves to the actual folder)
- No files were moved or copied - it's just an alternative path

## Quick Reference

**Symlink Path**: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2` (only needed when the original folder contains `#`)

**Original Path**: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2`

**Script Location**: `tools\create-symlink.ps1`

