# Cursor Settings Optimization - Fix for Hanging Issue

## Problem Identified

Cursor was hanging during the planning phase due to **excessive rule processing**. The workspace had **10 rules with `alwaysApply: true`**, which forced Cursor to process all of them on every single request, even when not relevant to the current task.

## Root Cause

1. **Too Many Always-Applied Rules**: 10 rules were set to `alwaysApply: true`
   - `project-docs-context.mdc` (applies to `**/*`)
   - `coding-standards.mdc`
   - `naming-conventions.mdc`
   - `ml-model-management.mdc`
   - `security-standards.mdc`
   - `logging-standards.mdc`
   - `error-handling.mdc`
   - `testing-requirements.mdc`
   - `git-workflow.mdc`
   - `documentation-organization.mdc`

2. **Redundant Processing**: These rules already had specific `globs` patterns that would trigger them when relevant files are edited. The `alwaysApply: true` flag was forcing them to be processed even when not needed.

3. **Planning Phase Overload**: During planning, Cursor was trying to process all these rules simultaneously, causing the hang.

## Solution Applied

Changed all rules from `alwaysApply: true` to `alwaysApply: false`. The rules will still apply automatically when:
- The file being edited matches the rule's `globs` pattern
- The rule is explicitly referenced in the conversation

## Changes Made

All 10 rules in `.cursor/rules/` were updated:
- ✅ `project-docs-context.mdc` - Changed to `alwaysApply: false`
- ✅ `coding-standards.mdc` - Changed to `alwaysApply: false`
- ✅ `naming-conventions.mdc` - Changed to `alwaysApply: false`
- ✅ `ml-model-management.mdc` - Changed to `alwaysApply: false`
- ✅ `security-standards.mdc` - Changed to `alwaysApply: false`
- ✅ `logging-standards.mdc` - Changed to `alwaysApply: false`
- ✅ `error-handling.mdc` - Changed to `alwaysApply: false`
- ✅ `testing-requirements.mdc` - Changed to `alwaysApply: false`
- ✅ `git-workflow.mdc` - Changed to `alwaysApply: false`
- ✅ `documentation-organization.mdc` - Changed to `alwaysApply: false`

## How Rules Still Work

Rules will still be applied automatically based on their `globs` patterns:

- **When editing Python files** (`.py`): Rules for Python (coding standards, naming, logging, error handling, security, testing) will apply
- **When editing TypeScript/React files** (`.ts`, `.tsx`): Rules for TypeScript (coding standards, naming, error handling, security, testing) will apply
- **When editing model files**: ML model management rules will apply
- **When editing markdown files**: Documentation organization rules will apply

## Expected Results

1. **Faster Planning**: Cursor should no longer hang during planning phase
2. **Faster Responses**: Less overhead from processing unnecessary rules
3. **Same Functionality**: Rules still apply when relevant, just more efficiently

## Verification

To verify the fix is working:
1. Restart Cursor (if it's currently running)
2. Try a simple coding task
3. Observe that planning completes quickly without hanging
4. Verify that rules still apply when editing relevant files

## Best Practices Going Forward

1. **Use `alwaysApply: false`** for most rules
2. **Rely on `globs` patterns** to trigger rules when needed
3. **Only use `alwaysApply: true`** for truly universal rules that must apply to everything
4. **Keep rules focused** - one rule per concern area
5. **Avoid redundancy** - Don't duplicate rules that are already in workspace rules

## Notes

- The workspace rules section in the system prompt already contains many of these standards, so there's some redundancy, but that's acceptable for clarity
- Rules with specific globs are more efficient than always-applied rules
- If you need a rule to always apply, consider if it really needs to be a rule or if it should be in the workspace rules section instead
