# Run System Audit

Run system audit (linting, tests, health checks).

## Usage

**In Cursor**: Type `/audit` in the command palette or chat. This executes `.cursor/commands/audit.py`, which delegates to the platform-specific audit script with proper error handling.

**Command Line**: Run before opening pull requests, cutting releases, or after major refactors.

**Related Commands**: See [docker-audit.md](docker-audit.md) for Docker-specific audits, [error.md](error.md) for quick diagnostics.

## Implementation

**Windows (PowerShell)**:

```powershell
.\tools\commands\audit.ps1
```

**Linux/macOS (Bash)**:

```bash
./tools/commands/audit.sh
```

**Cursor Command**:

When using `/audit` in Cursor, the command handler (`.cursor/commands/audit.py`) automatically:

1. Sets up proper output buffering and encoding
2. Validates project structure and script existence
3. Executes the platform-specific audit script (`.ps1` on Windows, `.sh` on Linux/macOS)
4. Handles errors with specific exception types
5. Ensures all output is visible

## What It Does

1. Checks Python code formatting (black)
2. Checks service health (backend API)
3. Checks logs for errors and warnings
4. Generates audit report

## Expected Output

- Audit results saved to `logs/audit/audit_<timestamp>.log`
- Formatting check results
- Health check results
- Error/warning summary from logs

## Notes

- **Cursor Integration**: The Python command handler provides consistent error handling and output formatting across platforms
- Attach `logs/audit/report.md` to the PR/issue when findings require discussion
- Run before PRs, releases, or after major refactors
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

