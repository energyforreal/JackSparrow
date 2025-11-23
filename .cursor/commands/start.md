# Start All Services

Launch all JackSparrow services (backend, agent, frontend).

## Usage

Run this command to start all services before every development session.

## Implementation

**Windows (PowerShell)**:
```powershell
.\tools\commands\start.ps1
```

**Linux/macOS (Bash)**:
```bash
./tools/commands/start.sh
```

**Makefile (Cross-platform)**:
```bash
make start
```

## What It Does

1. Creates logs directory
2. Starts Backend (FastAPI) on port 8000
3. Starts Agent (intelligent_agent)
4. Starts Frontend (Next.js) on port 3000

## Expected Output

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- Logs are in the `logs/` directory

## Notes

- Ensure `logs/start.log` is generated without errors
- Confirms backend, agent, and frontend are reachable on `localhost`
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

