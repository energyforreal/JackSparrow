# Restart All Services

Clean restart of all JackSparrow services.

## Usage

Trigger after changing environment variables, dependencies, or configuration files.

## Implementation

**Windows (PowerShell)**:
```powershell
.\tools\commands\restart.ps1
```

**Linux/macOS (Bash)**:
```bash
./tools/commands/restart.sh
```

**Makefile (Cross-platform)**:
```bash
make restart
```

## What It Does

1. Stops all running services (backend, agent, frontend)
2. Waits 2 seconds for clean shutdown
3. Starts all services fresh

## Expected Output

- Services stopped message
- Services restarted successfully
- Review `logs/restart.log` afterwards

## Notes

- Performs a clean shutdown and relaunch
- Review `logs/restart.log` after execution
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

