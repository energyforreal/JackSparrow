# Docker Logs Analysis

Analyze Docker container logs with filtering and export capabilities.

## Usage

**Related Commands**: See [docker-audit.md](docker-audit.md) for error auditing, [error.md](error.md) for quick diagnostics.

```bash
make docker-logs [SERVICE=backend] [LEVEL=ERROR] [TAIL=100]
# or
scripts/docker/logs.ps1 [service] [--Level ERROR] [--Tail 100] [--Follow] [--Export]
scripts/docker/logs.sh [service] [--level=ERROR] [--tail=100] [-f] [--export]
```

## Implementation

**Windows (PowerShell)**:
```powershell
.\scripts\docker\logs.ps1 [service] [-Level ERROR|WARNING|INFO|DEBUG|ALL] [-Tail 100] [-Follow] [-Export]
```

**Linux/macOS (Bash)**:
```bash
./scripts/docker/logs.sh [service] [--level=ERROR] [--tail=100] [-f] [--export]
```

## Parameters

- **`service`**: Service name (backend, agent, frontend, postgres, redis). Omit for all services.
- **`--Level` / `--level`**: Filter by log level (ERROR, WARNING, INFO, DEBUG, ALL). Default: ALL
- **`--Tail` / `--tail`**: Number of recent log lines to show. Default: 100
- **`--Follow` / `-f`**: Follow logs in real-time (like `tail -f`)
- **`--Export` / `--export`**: Export logs to file in `logs/docker-logs/`

## Examples

**View all backend logs:**
```bash
make docker-logs SERVICE=backend
scripts/docker/logs.ps1 backend
```

**View only errors from agent:**
```bash
make docker-logs SERVICE=agent LEVEL=ERROR
scripts/docker/logs.ps1 agent -Level ERROR
```

**Follow logs in real-time:**
```bash
scripts/docker/logs.ps1 backend -Follow
scripts/docker/logs.sh backend -f
```

**Export error logs:**
```bash
scripts/docker/logs.ps1 backend -Level ERROR -Export
scripts/docker/logs.sh backend --level=ERROR --export
```

**View last 500 lines with warnings:**
```bash
scripts/docker/logs.ps1 backend -Level WARNING -Tail 500
scripts/docker/logs.sh backend --level=WARNING --tail=500
```

## Output

- **Color-coded**: Errors (red), warnings (yellow), info (green)
- **Service prefixes**: Each log line shows which service it's from
- **Exported files**: Saved to `logs/docker-logs/logs-{service}-{level}-{timestamp}.log`

## Notes

- Logs are filtered client-side for better performance
- Export feature saves filtered logs to files for analysis
- Follow mode streams logs in real-time (press Ctrl+C to stop)
- Color coding helps identify error severity quickly
- Use export feature for sharing logs with team or for detailed analysis

