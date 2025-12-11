# Error Diagnostics

Quick diagnostic for runtime issues.

## Usage

**In Cursor**: Type `/error` in the command palette or chat. This executes `.cursor/commands/error.py`, which delegates to the platform-specific error diagnostics script with proper error handling.

**Command Line**: Execute when diagnosing runtime issues.

**Related Commands**: See [audit.md](audit.md) for comprehensive system audit, [docker-logs.md](docker-logs.md) for Docker container logs.

## Implementation

**Windows (PowerShell)**:

```powershell
.\tools\commands\error.ps1
```

**Linux/macOS (Bash)**:

```bash
./tools/commands/error.sh
```

**Cursor Command**:

When using `/error` in Cursor, the command handler (`.cursor/commands/error.py`) automatically:

1. Sets up proper output buffering and encoding
2. Validates project structure and script existence
3. Executes the platform-specific error diagnostics script (`.ps1` on Windows, `.sh` on Linux/macOS)
4. Handles errors with specific exception types
5. Ensures all output is visible

## What It Does

1. Checks service status (backend, agent)
2. Displays recent errors from logs
3. Generates error summary report

## Expected Output

- Service status (running/not running with PIDs)
- Recent errors (last 20 lines matching error/exception/traceback)
- Diagnostics saved to `logs/error/summary_<timestamp>.log`

## Notes

- **Cursor Integration**: The Python command handler provides consistent error handling and output formatting across platforms
- Share `logs/error/summary_<timestamp>.log` with the team if escalation is needed
- Use when diagnosing runtime issues
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

