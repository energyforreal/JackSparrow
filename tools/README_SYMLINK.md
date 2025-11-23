# Symlink Fix for Next.js Path Issue

## Overview

This directory contains scripts and documentation to fix the Next.js module resolution error caused by the `#` character in the folder name "Trading Agent#2".

## Problem

Next.js incorrectly parses file paths when the folder name contains a `#` character, causing it to look for `app-router.js#` instead of `app-router.js`. This happens in Next.js's internal file tracing system before webpack processes anything, so configuration changes don't fix it.

## Solution

Create a symbolic link (symlink) that provides an alternative path without the `#` character. The symlink points to your original folder, so no files are moved or copied.

## Quick Start

1. **Read the quick start guide**: `QUICK_START_SYMLINK.md`
2. **Or follow the detailed guide**: `SYMLINK_SETUP_GUIDE.md`

## Files

- **`create-symlink.ps1`** - PowerShell script to create the symlink (requires Administrator)
- **`verify-symlink-fix.ps1`** - Verification script to test if the fix worked
- **`SYMLINK_SETUP_GUIDE.md`** - Detailed step-by-step instructions
- **`QUICK_START_SYMLINK.md`** - Quick reference for setup
- **`QUICK_FIX.md`** - Overview of all available solutions

## What the Symlink Does

- **Source (original)**: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent#2`
- **Symlink (new path)**: `C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2`
- **Result**: Both paths access the same files, but Next.js uses the clean path without `#`

## Important Notes

- Always use the symlink path (`Trading-Agent-2`) for development
- The original folder stays as-is - no files are moved
- Requires Administrator privileges to create the symlink
- Once created, works transparently - Git and all tools work normally

## Verification

After creating the symlink and switching to it:

```powershell
.\tools\verify-symlink-fix.ps1
```

This will:
1. Check that you're using the symlink path
2. Clear the Next.js build cache
3. Test the Next.js build
4. Report success or failure

## Troubleshooting

See `SYMLINK_SETUP_GUIDE.md` for detailed troubleshooting steps.

