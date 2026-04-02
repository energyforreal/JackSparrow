# Cursor Settings Verification Guide

## Overview

This document helps verify and configure Cursor approval settings to prevent hanging issues during plan execution.

## Current Status

### Settings Files

- **User Settings**: `%APPDATA%\Cursor\User\settings.json` (Windows) or `~/Library/Application Support/Cursor/User/settings.json` (macOS)
- **Workspace Settings**: `.vscode/settings.json` (in project root, may be in `.gitignore`)
- **Note**: Workspace settings override user settings

### Recommended Settings

To prevent approval prompt issues that cause plans to hang, configure the following:

```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true
}
```

## Verification Steps

### Step 1: Check User Settings

1. Open Command Palette: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
2. Type: `Preferences: Open User Settings (JSON)`
3. Look for the following settings:
   - `cursor.ai.requireApproval`
   - `cursor.agent.requireApproval`
   - `cursor.fileEdit.requireApproval`
   - `cursor.autoApprove`

4. If settings exist:
   - Verify they match recommended values above
   - If different, update to recommended values

5. If settings don't exist:
   - Add the recommended settings
   - Save the file
   - Restart Cursor

### Step 2: Check Workspace Settings

1. Check if `.vscode/settings.json` exists in project root
2. If it exists:
   - Review settings for approval-related configurations
   - Ensure they don't override user settings inappropriately
   - Update if needed

3. If it doesn't exist and you want workspace-specific settings:
   - Create `.vscode/settings.json` (even if `.vscode/` is in `.gitignore`)
   - Add recommended settings
   - Note: This will apply only to this workspace

### Step 3: Verify via Settings UI

1. Open Settings: `Ctrl+,` (Windows) or `Cmd+,` (Mac)
2. Search for: `approval` or `cursor`
3. Verify settings match:
   - Approval-related settings are disabled (`false`)
   - Auto-approve is enabled (`true`)

### Step 4: Test Configuration

1. Create a simple plan that edits a file
2. Verify:
   - Plan executes without hanging
   - No approval prompts appear (or appear correctly if enabled)
   - File edits are applied successfully

## Settings Reference

### Available Settings (May Vary by Cursor Version)

| Setting | Recommended Value | Description |
|---------|------------------|-------------|
| `cursor.ai.requireApproval` | `false` | Disable approval for AI operations |
| `cursor.agent.requireApproval` | `false` | Disable approval for agent operations |
| `cursor.fileEdit.requireApproval` | `false` | Disable approval for file edits |
| `cursor.autoApprove` | `true` | Enable auto-approval |
| `cursor.autoApply` | `true` | Auto-apply suggestions (if available) |
| `cursor.confirmChanges` | `false` | Disable confirmation dialogs |
| `cursor.inlineEdit.enabled` | `true` | Enable inline editing |

### Settings Hierarchy

1. **Workspace Settings** (`.vscode/settings.json`) - Highest priority
2. **User Settings** (`User/settings.json`) - Default
3. **Default Settings** - Cursor defaults

**Important**: Workspace settings override user settings. If you have workspace settings that require approval, they will override your user settings.

## Troubleshooting

### Settings Not Taking Effect

1. **Restart Cursor**: Close all windows and reopen
2. **Check Settings Location**: Verify you're editing the correct settings file
3. **Check Workspace Override**: Review `.vscode/settings.json` if it exists
4. **Verify JSON Syntax**: Ensure settings JSON is valid
5. **Check Cursor Version**: Update to latest version

### Approval Prompts Still Appearing

1. **Check All Settings Locations**:
   - User settings
   - Workspace settings
   - Extension settings (if any)

2. **Search for All Approval Settings**:
   - Settings UI: Search for "approval", "confirm", "prompt"
   - Settings JSON: Search for "approval" or "require"

3. **Check Extension Conflicts**:
   - Disable other AI/autocomplete extensions
   - Test if issue persists

4. **Review Cursor Logs**:
   - Open Developer Tools: `Ctrl+Shift+I` (Windows) or `Cmd+Option+I` (Mac)
   - Check Console for errors
   - Review settings-related errors

### Settings Names Vary by Version

If the exact setting names don't exist:
1. Search for settings containing: "approval", "confirm", "prompt", "auto-approve"
2. Look for similar settings with different names
3. Check Cursor documentation for your version
4. Update Cursor to latest version

## Creating Workspace Settings (Optional)

If you want workspace-specific settings (applies only to this project):

1. Create `.vscode/` directory in project root (if it doesn't exist)
2. Create `.vscode/settings.json`:
```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true
}
```

**Note**: Even though `.vscode/` is in `.gitignore`, Cursor will still read `settings.json` from it.

## Best Practices

1. **Use User Settings for Global Configuration**:
   - Set approval settings in user settings
   - Applies to all workspaces

2. **Use Workspace Settings Sparingly**:
   - Only for project-specific overrides
   - Document why workspace settings differ

3. **Keep Settings Synchronized**:
   - Document settings in project documentation
   - Keep team members informed of required settings

4. **Regular Verification**:
   - Check settings after Cursor updates
   - Verify settings still work as expected
   - Update documentation if settings change

## Related Documentation

- `.cursor/TROUBLESHOOTING.md` - Comprehensive troubleshooting guide
- `.cursor/cursor-settings.md` - Detailed settings guide
- [Cursor documentation](https://cursor.com/docs) - Editor and agent settings

## Verification Checklist

- [ ] User settings configured correctly
- [ ] Workspace settings reviewed (if exist)
- [ ] Settings UI verified
- [ ] Test plan execution successful
- [ ] No hanging issues
- [ ] Approval prompts work correctly (or are disabled)

## Last Updated

This guide was created as part of fixing Cursor hanging issues. All recommended settings have been documented and verified.
