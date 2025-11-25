# Docker Error Audit

Scan all Docker container logs for errors and generate comprehensive audit reports.

## Usage

**Related Commands**: See [audit.md](audit.md) for system-wide audit, [docker-logs.md](docker-logs.md) for log viewing.

```bash
make docker-audit
# or
scripts/docker/audit-errors.ps1
scripts/docker/audit-errors.sh
```

## Implementation

**Windows (PowerShell)**:
```powershell
.\scripts\docker\audit-errors.ps1 [-Hours 24] [-OutputDir "logs/docker-audit"]
```

**Linux/macOS (Bash)**:
```bash
./scripts/docker/audit-errors.sh [--hours=24] [--output-dir="logs/docker-audit"]
```

## Parameters

- **`--Hours` / `--hours`**: Time range to scan (hours). Default: 24
- **`--OutputDir` / `--output-dir`**: Directory for audit reports. Default: `logs/docker-audit`

## What It Does

1. Scans logs from all services (backend, agent, frontend, postgres, redis)
2. Categorizes errors by type:
   - Python exceptions
   - Python tracebacks
   - General errors
   - Failed operations
   - Connection errors
   - Timeout errors
   - Database errors
   - Redis errors
   - HTTP 5xx errors
   - HTTP 4xx errors
3. Generates markdown report with:
   - Error counts per category
   - Sample error messages
   - Unique error identification
   - Actionable recommendations

## Output

Report saved to: `logs/docker-audit/audit-{timestamp}.md`

Report includes:
- **Summary**: Total services audited, error counts
- **Per-service analysis**: Error categories and samples
- **Recommendations**: Actionable steps for error resolution

## Examples

**Audit last 24 hours (default):**
```bash
make docker-audit
scripts/docker/audit-errors.ps1
```

**Audit last 48 hours:**
```bash
scripts/docker/audit-errors.ps1 -Hours 48
scripts/docker/audit-errors.sh --hours=48
```

**Custom output directory:**
```bash
scripts/docker/audit-errors.ps1 -OutputDir "logs/custom-audit"
scripts/docker/audit-errors.sh --output-dir="logs/custom-audit"
```

## Interpreting Reports

### Error Categories

- **High Priority**: Exceptions, tracebacks, connection errors
- **Medium Priority**: Failed operations, timeout errors
- **Low Priority**: HTTP 4xx errors (may be expected)

### Recommendations

The report provides:
- Pattern identification for recurring errors
- Service-specific error analysis
- Suggested debugging steps
- Health check review prompts

## Notes

- Run regularly (daily/weekly) to catch issues early
- Share audit reports with team for error pattern analysis
- Use before deployments to ensure system health
- Reports are timestamped for historical tracking
- Zero errors reported means clean logs in the time range
- Review high-frequency errors first for maximum impact

