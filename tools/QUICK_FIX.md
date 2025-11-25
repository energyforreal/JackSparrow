# Quick Fix for Next.js Path Error with # Character

## Problem
The `#` character in your folder name (e.g., `Trading Agent#2`) causes Next.js to incorrectly parse paths, looking for `app-router.js#` instead of `app-router.js`. This happens in Next.js's internal file tracing system before webpack processes anything.

> **Already on `Trading Agent 2`?**  
> If your project directory no longer contains `#` (the repo now ships as `Trading Agent 2`), you can skip this entire workaround—the issue is already resolved. The scripts below will detect this and exit gracefully.

## Solution: Create Symlink (Recommended - No Data Movement)

**Status**: ✅ Implementation ready - follow the guide below.

1. **Open PowerShell as Administrator**
   - Right-click PowerShell → "Run as Administrator"

2. **Navigate to your project folder**
   ```powershell
   cd "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent 2"
   ```

3. **Create the symlink (only needed if the folder still includes `#`)**
   ```powershell
   .\tools\create-symlink.ps1
   ```

4. **Reopen Cursor/VS Code** and open the project from:
   ```
   C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2
   ```

5. **Verify the fix**:
   ```powershell
   .\tools\verify-symlink-fix.ps1
   ```
   Or manually test:
   ```powershell
   cd frontend
   npm run build
   ```

**For detailed instructions, see**: `tools/SYMLINK_SETUP_GUIDE.md`  
**For quick reference, see**: `tools/QUICK_START_SYMLINK.md`

---

## Solution 2: Rename Folder (Permanent Fix)

1. **Close all applications** using files from the project
2. **Rename the folder** from "Trading Agent#2" to "Trading-Agent-2"
3. **Reopen the project** from the new location

## Why This Happens

The `#` character has special meaning in URLs (fragment identifier). Next.js's internal path resolution on Windows incorrectly treats it as part of the URL, causing module paths to be malformed with null bytes or incorrect parsing.

## Verification

After applying either solution, run:
```powershell
cd frontend
npm run build
```

If the build succeeds, the issue is resolved!

