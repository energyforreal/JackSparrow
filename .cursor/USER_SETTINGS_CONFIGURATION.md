# Cursor User Settings Configuration Guide

## Overview

This guide provides step-by-step instructions for configuring Cursor User Settings to disable approval prompts and prevent hanging issues.

## Why User Settings Are Critical

- Workspace settings (`.vscode/settings.json`) only apply to the current project
- User settings apply globally to all Cursor workspaces
- Some Cursor features require user-level settings to function properly
- User settings can override workspace settings in some cases

## Step-by-Step Configuration

### Method 1: Via Settings JSON (Recommended)

#### Step 1: Open Command Palette

- **Windows/Linux**: Press `Ctrl+Shift+P`
- **macOS**: Press `Cmd+Shift+P`

#### Step 2: Open User Settings JSON

1. Type: `Preferences: Open User Settings (JSON)`
2. Press Enter
3. A JSON file will open in the editor

#### Step 3: Add Settings

Add the following settings to your User Settings JSON file. If the file already has content, add these settings inside the existing JSON object (don't duplicate the opening/closing braces):

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

**Important**: If you already have settings in the file, merge these settings with your existing ones. Don't create duplicate JSON objects.

#### Step 4: Save and Restart

1. Save the file (`Ctrl+S` or `Cmd+S`)
2. **Completely close Cursor** (close all windows)
3. Wait a few seconds
4. Reopen Cursor
5. Test by asking Cursor to create or edit a file

### Method 2: Via Settings UI

#### Step 1: Open Settings

- **Windows/Linux**: Press `Ctrl+,`
- **macOS**: Press `Cmd+,`
- Or: `File` → `Preferences` → `Settings`

#### Step 2: Search for Approval Settings

1. In the settings search box, type: `approval`
2. Look for settings containing:
   - "Require Approval"
   - "Ask for Approval"
   - "Auto Approve"

#### Step 3: Configure Settings

For each setting found:

- **`cursor.ai.requireApproval`** → Set to `false` or uncheck
- **`cursor.agent.requireApproval`** → Set to `false` or uncheck
- **`cursor.fileEdit.requireApproval`** → Set to `false` or uncheck
- **`cursor.autoApprove`** → Set to `true` or check
- **`cursor.autoApply`** → Set to `true` or check
- **`cursor.confirmChanges`** → Set to `false` or uncheck

#### Step 4: Search for Additional Settings

1. Search for: `cursor inline`
2. Enable: `cursor.inlineEdit.enabled` → Set to `true`

#### Step 5: Restart Cursor

1. Close all Cursor windows completely
2. Wait a few seconds
3. Reopen Cursor
4. Test the configuration

## Settings Reference

### Required Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| `cursor.ai.requireApproval` | `false` | Disable approval for AI operations |
| `cursor.agent.requireApproval` | `false` | Disable approval for agent operations |
| `cursor.fileEdit.requireApproval` | `false` | Disable approval for file edits |
| `cursor.autoApprove` | `true` | Enable automatic approval |
| `cursor.autoApply` | `true` | Auto-apply suggestions |
| `cursor.confirmChanges` | `false` | Disable confirmation dialogs |
| `cursor.inlineEdit.enabled` | `true` | Enable inline editing |

### Optional Settings (May Not Exist in All Versions)

- `cursor.chat.requireApproval` → `false`
- `cursor.composer.requireApproval` → `false`
- `cursor.plan.requireApproval` → `false`

## User Settings File Locations

### Windows
```
%APPDATA%\Cursor\User\settings.json
```
Typically: `C:\Users\<YourUsername>\AppData\Roaming\Cursor\User\settings.json`

### macOS
```
~/Library/Application Support/Cursor/User/settings.json
```

### Linux
```
~/.config/Cursor/User/settings.json
```

## Verification

After configuring settings and restarting Cursor:

1. **Test File Creation**:
   - Ask Cursor to create a new file
   - Verify it creates without approval prompts

2. **Test File Editing**:
   - Ask Cursor to edit an existing file
   - Verify edits are applied automatically

3. **Check for Hanging**:
   - Try multiple operations
   - Verify no "awaiting approval" messages appear
   - Confirm operations complete successfully

## Troubleshooting

### Settings Not Taking Effect

1. **Verify JSON Syntax**: Ensure the JSON is valid (no trailing commas, proper quotes)
2. **Check File Location**: Confirm you edited the correct User Settings file
3. **Restart Cursor**: Completely close and reopen Cursor
4. **Check Workspace Settings**: Verify `.vscode/settings.json` doesn't conflict

### Still Seeing Approval Prompts

1. **Check All Settings**: Search for "approval" in Settings UI and disable all
2. **Check Extensions**: Some extensions may add approval layers
3. **Update Cursor**: Help → Check for Updates
4. **Clear Cache**: See `.cursor/TROUBLESHOOTING.md` for cache locations

### Settings File Not Found

1. **Create It**: If the file doesn't exist, create it with the settings above
2. **Check Permissions**: Ensure you have write permissions to the directory
3. **Use Settings UI**: If JSON editing fails, use the Settings UI method instead

## Settings Hierarchy

1. **Workspace Settings** (`.vscode/settings.json`) - Highest priority for workspace
2. **User Settings** (`User/settings.json`) - Global defaults
3. **Default Settings** - Cursor defaults

**Note**: Both workspace and user settings should be configured for best results.

## Additional Resources

- `CURSOR_AUTO_APPROVE_SETUP.md` - Quick reference guide
- `.cursor/TROUBLESHOOTING.md` - Comprehensive troubleshooting
- `.cursor/cursor-settings.md` - Detailed settings documentation
- `.cursor/SETTINGS_VERIFICATION.md` - Settings verification guide

---

**Last Updated**: Configuration guide for fixing Cursor hanging issues

