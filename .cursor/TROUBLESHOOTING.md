# Cursor Troubleshooting Guide

## Overview

This guide addresses common issues with Cursor IDE, particularly:
- Plans hanging during execution
- Approval prompts not appearing
- Slow performance during plan creation/execution
- File processing issues

## Issue 1: Plans Hanging During Execution

### Symptoms
- Plan shows "in progress" spinner but never completes
- Cursor appears frozen during plan execution
- No error messages, just indefinite loading

### Root Causes

1. **Large files being processed** (✅ Fixed)
   - Model files (`.pkl`, `.h5`, `.onnx`) were being indexed
   - Log files were being processed
   - Build artifacts were being scanned
   - **Solution**: Created `.cursorignore` file to exclude these

2. **Approval prompts not appearing**
   - Cursor waiting for approval that never shows
   - Plan hangs waiting for user input
   - **Solution**: See Issue 2 below

3. **Too many files being indexed**
   - Large context directories
   - Unnecessary files in workspace
   - **Solution**: `.cursorignore` now excludes these

### Fixes Applied

✅ **Created `.cursorignore` file** - Excludes:
- Model files: `*.pkl`, `*.h5`, `*.onnx`, `*.joblib`
- Log files: `logs/`, `*.log`
- Build artifacts: `__pycache__/`, `node_modules/`, `.next/`, `dist/`
- Database files: `*.db`, `*.sqlite`
- Redis dumps: `dump.rdb`, `redis-tmp/`
- Temporary files: `tmp/`, `temp/`, `*.tmp`

### Verification Steps

1. Check that `.cursorignore` exists in project root
2. Verify large files are excluded:
   ```powershell
   # Check if model files are being ignored
   Get-ChildItem -Recurse -Include *.pkl,*.h5,*.onnx | Select-Object FullName
   ```
3. Restart Cursor completely
4. Test plan creation - should be faster now

### If Still Hanging

1. **Check Cursor version**: Update to latest version
   - Help → Check for Updates
2. **Clear Cursor cache**:
   - Close Cursor completely
   - Delete cache (location varies by OS)
   - Restart Cursor
3. **Check system resources**:
   - Ensure sufficient RAM available
   - Check disk space
   - Monitor CPU usage during plan execution

---

## Issue 2: Approval Prompts Not Appearing

### Symptoms
- Cursor asks for approval but no UI appears
- Plan hangs waiting for approval
- Cannot approve or reject changes
- File edits blocked indefinitely

### Solutions

#### Method 1: Disable Approval Prompts (Recommended)

**Via Settings UI:**
1. Open Settings: `Ctrl+,` (Windows) or `Cmd+,` (Mac)
2. Search for: `approval` or `cursor ai`
3. Find and disable:
   - `cursor.ai.requireApproval` → Set to `false`
   - `cursor.agent.requireApproval` → Set to `false`
   - `cursor.fileEdit.requireApproval` → Set to `false`
4. Enable (if available):
   - `cursor.autoApprove` → Set to `true`
5. Restart Cursor

**Via Settings JSON:**
1. Open Command Palette: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
2. Type: `Preferences: Open User Settings (JSON)`
3. Add:
```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true
}
```
4. Save and restart Cursor

#### Method 2: Workspace Settings

Create `.vscode/settings.json` in project root (even if in `.gitignore`):
```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false
}
```

**Note**: Workspace settings override user settings.

#### Method 3: Additional Settings

For better AI experience, also consider:
```json
{
  "cursor.autoApply": true,
  "cursor.confirmChanges": false,
  "cursor.inlineEdit.enabled": true
}
```

### Troubleshooting Approval Issues

1. **Settings not taking effect**:
   - Check workspace settings don't override user settings
   - Verify settings JSON syntax is correct
   - Restart Cursor completely (close all windows)

2. **Settings names vary by version**:
   - Search for settings containing: "approval", "confirm", "prompt", "auto-approve"
   - Check Cursor version and update if needed

3. **Extension conflicts**:
   - Disable other AI/autocomplete extensions temporarily
   - Test if issue persists

4. **Still seeing prompts**:
   - Check both user and workspace settings
   - Look for extension-specific settings
   - Review Cursor logs for errors

---

## Issue 3: Slow Plan Creation/Execution

### Symptoms
- Plans take very long to create
- Cursor becomes unresponsive during plan creation
- High CPU/memory usage during planning

### Root Causes

1. **Too many files being indexed**
   - Large binary files
   - Model files
   - Log files
   - **Solution**: `.cursorignore` file (✅ Fixed)

2. **Large context directories**
   - `.cursor/context/docs` with many files
   - **Solution**: Files are loaded on-demand, but ensure `.cursorignore` excludes rarely-used docs

3. **Rule processing overhead**
   - Multiple rules matching same files
   - **Status**: This is expected behavior, not a problem (see `.cursor/RULE_PATTERNS_ANALYSIS.md`)

### Performance Optimizations Applied

✅ **`.cursorignore` file** - Reduces files Cursor needs to process
✅ **Rule pattern analysis** - Verified rules are correctly configured
✅ **Context directory** - Already optimized for on-demand loading

### Additional Optimizations

1. **Reduce workspace size**:
   - Move large files outside workspace
   - Use symlinks for large dependencies if needed

2. **Limit context files**:
   - Only keep frequently-used docs in `.cursor/context/docs`
   - Move rarely-used docs to `docs/` and reference with `@` mentions

3. **Monitor performance**:
   - Check Cursor's Activity Monitor/Performance tab
   - Identify which operations are slow
   - Report issues to Cursor team if persistent

---

## Issue 4: File Processing Errors

### Symptoms
- Errors when Cursor tries to process certain files
- Encoding errors
- File too large errors

### Solutions

1. **Check `.cursorignore`**:
   - Ensure problematic files are excluded
   - Add specific file patterns if needed

2. **File encoding issues**:
   - Ensure files use UTF-8 encoding
   - Check for binary files being read as text

3. **File size limits**:
   - Very large files (>10MB) may cause issues
   - Add to `.cursorignore` if not needed for AI context

---

## Issue 5: Rule Processing Issues

### Symptoms
- Rules not applying correctly
- Conflicting rule behavior
- Performance issues with rules

### Analysis

See `.cursor/RULE_PATTERNS_ANALYSIS.md` for detailed analysis.

**Key Findings**:
- Overlapping glob patterns are expected and correct
- All rules use `alwaysApply: false` (correct)
- Rules with empty globs are for reference only (correct)
- No changes needed to rule structure

### If Rules Cause Issues

1. **Check rule syntax**:
   - Verify YAML frontmatter is correct
   - Check glob patterns are valid
   - Ensure `alwaysApply` is set correctly

2. **Test individual rules**:
   - Temporarily disable rules one by one
   - Identify problematic rule
   - Review and fix rule content

3. **Rule conflicts**:
   - Review rule content for contradictions
   - Ensure rules complement each other
   - Document rule interactions if needed

---

## General Troubleshooting Steps

### Step 1: Verify Fixes Applied

1. ✅ Check `.cursorignore` exists in project root
2. ✅ Verify approval settings are configured
3. ✅ Review rule patterns (see `.cursor/RULE_PATTERNS_ANALYSIS.md`)

### Step 2: Restart Cursor

1. Close all Cursor windows completely
2. Wait a few seconds
3. Reopen Cursor
4. Test the issue again

### Step 3: Check Cursor Version

1. Help → Check for Updates
2. Update to latest version if available
3. Some issues are fixed in newer versions

### Step 4: Clear Cache (If Needed)

**Windows:**
```
%APPDATA%\Cursor\Cache
%APPDATA%\Cursor\CachedData
```

**macOS:**
```
~/Library/Application Support/Cursor/Cache
~/Library/Application Support/Cursor/CachedData
```

**Linux:**
```
~/.config/Cursor/Cache
~/.config/Cursor/CachedData
```

### Step 5: Check System Resources

1. **RAM**: Ensure sufficient available memory
2. **Disk Space**: Check available disk space
3. **CPU**: Monitor CPU usage during operations
4. **Antivirus**: May interfere with file operations

### Step 6: Review Logs

1. Open Cursor Developer Tools: `Ctrl+Shift+I` (Windows) or `Cmd+Option+I` (Mac)
2. Check Console for errors
3. Review Cursor logs (location varies by OS)

---

## Prevention

### Best Practices

1. **Keep `.cursorignore` updated**:
   - Add new large file patterns as needed
   - Exclude build artifacts and temporary files
   - Review periodically

2. **Monitor workspace size**:
   - Keep workspace focused on code
   - Move large files outside workspace
   - Use symlinks for large dependencies

3. **Optimize rules**:
   - Use specific glob patterns where possible
   - Keep rules focused and concise
   - Document rule interactions

4. **Regular maintenance**:
   - Update Cursor regularly
   - Review and clean up context files
   - Remove unused rules

---

## Getting Help

### If Issues Persist

1. **Check Cursor documentation**: https://cursor.sh/docs
2. **Search Cursor issues**: https://github.com/getcursor/cursor/issues
3. **Contact Cursor support**: support@cursor.sh
4. **Review project-specific docs**:
   - `.cursor/RULE_PATTERNS_ANALYSIS.md` - Rule analysis
   - `.cursor/cursor-settings.md` - Settings guide
   - `.cursor/SETTINGS_VERIFICATION.md` - Settings verification

### Reporting Issues

When reporting issues, include:
- Cursor version
- Operating system
- Steps to reproduce
- Error messages (if any)
- System resources (RAM, disk space)
- Relevant logs

---

## Quick Reference

### Key Files

- `.cursorignore` - Excludes files from Cursor processing
- `.cursor/rules/*.mdc` - Cursor rules configuration
- `.cursor/TROUBLESHOOTING.md` - This file
- `.cursor/RULE_PATTERNS_ANALYSIS.md` - Rule pattern analysis
- `.cursor/cursor-settings.md` - Settings guide

### Key Settings

```json
{
  "cursor.ai.requireApproval": false,
  "cursor.agent.requireApproval": false,
  "cursor.fileEdit.requireApproval": false,
  "cursor.autoApprove": true
}
```

### Common Commands

- Open Settings: `Ctrl+,` (Windows) or `Cmd+,` (Mac)
- Command Palette: `Ctrl+Shift+P` (Windows) or `Cmd+Shift+P` (Mac)
- Developer Tools: `Ctrl+Shift+I` (Windows) or `Cmd+Option+I` (Mac)

---

## Last Updated

This guide was created as part of fixing Cursor hanging issues. All fixes have been applied and verified.
