# Cursor IDE Settings - Disable Approval Prompts

## Quick Fix: Disable File Edit/Creation Approval Prompts

To stop Cursor from asking for approval on every file edit or creation:

### Method 1: Via Cursor Settings UI

1. **Open Cursor Settings:**
   - Press `Ctrl+,` (Windows/Linux) or `Cmd+,` (Mac)
   - Or go to: `File` → `Preferences` → `Settings`

2. **Search for approval settings:**
   - Type "approval" or "file edit" in the settings search box
   - Look for settings like:
     - `cursor.ai.requireApproval`
     - `cursor.agent.requireApproval`
     - `cursor.fileEdit.requireApproval`
     - `cursor.autoApprove`

3. **Disable approval prompts:**
   - Set any "requireApproval" settings to `false`
   - Enable "autoApprove" if available

### Method 2: Via Settings JSON

1. **Open Settings JSON:**
   - Press `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (Mac)
   - Type "Preferences: Open User Settings (JSON)"
   - Press Enter

2. **Add these settings:**
```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true
}
```

### Method 3: Via Workspace Settings (This Project Only)

Add a `.vscode/settings.json` file to your project (even though it's in .gitignore, Cursor will still read it):

```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false
}
```

## Additional Settings for Better AI Experience

You may also want to adjust these related settings:

```json
{
  // Disable approval prompts
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  
  // Auto-apply suggestions (if available)
  "cursor.autoApply": true,
  
  // Reduce confirmation dialogs
  "cursor.confirmChanges": false,
  
  // Enable inline editing without prompts
  "cursor.inlineEdit.enabled": true
}
```

## Troubleshooting

If you still see approval prompts after making these changes:

1. **Restart Cursor** completely
2. **Check workspace vs user settings** - workspace settings may override user settings
3. **Check for extension conflicts** - some extensions may add their own approval layers
4. **Look for Cursor-specific settings** in Settings UI - search for "Cursor" to see all Cursor-related options

## Note

Settings names may vary depending on your Cursor version. If the above settings don't exist, look for similar settings with names containing:
- "approval"
- "confirm"
- "prompt"
- "auto-approve"
- "file edit"
- "apply changes"
