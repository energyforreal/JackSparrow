# Cursor Auto-Approve Setup - Fix Hanging Issues

## ⚠️ CRITICAL: You Must Configure User Settings

**Workspace settings alone are NOT sufficient.** You MUST also configure your Cursor User Settings to prevent hanging.

## Quick Fix (5 Minutes)

### Step 1: Open User Settings JSON

1. Press `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
2. Type: `Preferences: Open User Settings (JSON)`
3. Press Enter

### Step 2: Add These Settings

Copy and paste these settings into your User Settings JSON file:

```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true,
  "cursor.autoApply": true,
  "cursor.confirmChanges": false,
  "cursor.inlineEdit.enabled": true
}
```

### Step 3: Save and Restart

1. Save the file (`Ctrl+S`)
2. **Completely close Cursor** (close all windows)
3. Reopen Cursor
4. Test by asking Cursor to create or edit a file

## Why This Is Necessary

- **Workspace settings** (`.vscode/settings.json`) only apply to this project
- **User settings** apply globally and can override workspace settings
- Cursor may require BOTH to be configured to prevent hanging

## Verification

After restarting Cursor:

1. Try asking Cursor to create a new file
2. Try asking Cursor to edit an existing file
3. Verify that:
   - ✅ No approval prompts appear
   - ✅ Files are created/edited automatically
   - ✅ No hanging or "awaiting approval" messages

## If Still Hanging

1. **Check Settings UI**: Press `Ctrl+,` → Search for "approval" → Disable all "Require Approval" settings
2. **Update Cursor**: Help → Check for Updates
3. **Clear Cache**: See `.cursor/TROUBLESHOOTING.md` for cache locations
4. **Check Extensions**: Disable other AI/autocomplete extensions temporarily

## Additional Resources

- `.cursor/TROUBLESHOOTING.md` - Comprehensive troubleshooting guide
- `.cursor/cursor-settings.md` - Detailed settings documentation
- [Settings quick fix](settings-quick-fix.md) - Alternative methods

---

**Remember**: User Settings are REQUIRED. Workspace settings alone won't fix the hanging issue.

