# Run System Audit

Run system audit (linting, tests, health checks).

## Usage

Run before opening pull requests, cutting releases, or after major refactors.

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

- Attach `logs/audit/report.md` to the PR/issue when findings require discussion
- Run before PRs, releases, or after major refactors
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

