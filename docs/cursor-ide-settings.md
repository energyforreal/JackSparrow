# Cursor IDE Configuration Guide

## Disabling File Edit/Creation Approval Prompts

If Cursor is asking for approval on every file edit or creation, you can disable this behavior.

### Quick Steps

1. **Open Cursor Settings** (`Ctrl+,` or `Cmd+,`)
2. Search for "approval" or "cursor"
3. Disable any settings that say "requireApproval"
4. Enable "autoApprove" if available
5. Restart Cursor

### Detailed Instructions

See `.cursor/cursor-settings.md` for complete instructions and troubleshooting.

### Workspace Settings

This project includes a `.vscode/settings.json` file with recommended Cursor settings. Even though `.vscode/` is in `.gitignore`, Cursor will still read these settings for this workspace.

## Recommended Settings for Development

For the best development experience with Cursor AI:

- ✅ Disable approval prompts for file operations
- ✅ Enable auto-apply for simple edits
- ✅ Allow inline editing
- ✅ Reduce confirmation dialogs

These settings make Cursor more productive by allowing it to make changes without interrupting your workflow.
