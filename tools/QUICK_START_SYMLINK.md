# Quick Start - Symlink Setup

## TL;DR - Fast Setup

> **Note:** If your folder name no longer contains `#` (current repo default), the script will immediately let you know and no changes are necessary.

1. **Close Cursor completely** (File → Exit)

2. **Open PowerShell as Administrator**:
   - Windows Key → Type "PowerShell" → Right-click → "Run as Administrator"

3. **Run the script** (it auto-detects whether a `#` fix is needed):
   ```powershell
   cd "C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading Agent 2"
   .\tools\create-symlink.ps1
   ```

4. **Reopen Cursor** and open the project from:
   ```
   C:\Users\lohit\OneDrive\Documents\ATTRAL\Projects\Trading-Agent-2
   ```

5. **Test it works**:
   ```powershell
   cd frontend
   if (Test-Path .next) { Remove-Item -Recurse -Force .next }
   npm run build
   ```

Done! The Next.js error should be resolved.

For detailed instructions, see `SYMLINK_SETUP_GUIDE.md`.

