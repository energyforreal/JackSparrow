# Error Diagnostics

Quick diagnostic for runtime issues.

## Usage

Execute when diagnosing runtime issues.

## Implementation

**Windows (PowerShell)**:
```powershell
.\tools\commands\error.ps1
```

**Linux/macOS (Bash)**:
```bash
./tools/commands/error.sh
```

**Makefile (Cross-platform)**:
```bash
make error
```

## What It Does

1. Checks service status (backend, agent)
2. Displays recent errors from logs
3. Generates error summary report

## Expected Output

- Service status (running/not running with PIDs)
- Recent errors (last 20 lines matching error/exception/traceback)
- Diagnostics saved to `logs/error/summary_<timestamp>.log`

## Notes

- Share `logs/error/error-dump-<timestamp>.md` with the team if escalation is needed
- Use when diagnosing runtime issues
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

