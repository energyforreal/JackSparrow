# Restart All Services

Clean restart of all JackSparrow services.

## Usage

**In Cursor**: Type `/restart` in the command palette or chat. This executes `.cursor/commands/restart.py`, which delegates to the platform-specific restart script with proper error handling.

**Command Line**: Trigger after changing environment variables, dependencies, or configuration files.

**Related Commands**: See [start.md](start.md) for initial startup, [error.md](error.md) for diagnostics.

## Implementation

**Windows (PowerShell)**:

```powershell
.\tools\commands\restart.ps1
```

**Linux/macOS (Bash)**:

```bash
./tools/commands/restart.sh
```

**Cursor Command**:

When using `/restart` in Cursor, the command handler (`.cursor/commands/restart.py`) automatically:

1. Sets up proper output buffering and encoding
2. Validates project structure and script existence
3. Executes the platform-specific restart script (`.ps1` on Windows, `.sh` on Linux/macOS)
4. Handles errors with specific exception types
5. Ensures all output is visible

## What It Does

1. Stops all running services (backend, agent, frontend)
2. Waits 2 seconds for clean shutdown
3. Starts all services fresh

## Expected Output

- Services stopped message
- Services restarted successfully
- Review `logs/restart.log` afterwards

## Notes

- **Cursor Integration**: The Python command handler provides consistent error handling and output formatting across platforms
- Performs a clean shutdown and relaunch
- Review `logs/restart.log` after execution
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

