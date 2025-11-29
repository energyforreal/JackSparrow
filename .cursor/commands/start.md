# Start All Services

Launch all JackSparrow services (backend, agent, frontend).

## Prerequisites

Before running the start command, ensure the following prerequisites are met:

- **PostgreSQL 15+** with TimescaleDB extension must be installed and running
- **Redis 7+** must be installed and running
- **Database** must be created and migrations run (see `scripts/setup_db.py`)
- **Environment variables** must be configured (`.env` file in project root)
  - `DATABASE_URL` - PostgreSQL connection string
  - `REDIS_URL` - Redis connection string (defaults to `redis://localhost:6379`)
  - `DELTA_EXCHANGE_API_KEY` and `DELTA_EXCHANGE_API_SECRET` - Required for trading

> ℹ️ The Windows/Linux startup scripts will attempt to launch a local Redis instance automatically if `REDIS_URL` is unreachable. You should still keep your preferred Redis service installed so the fallback is only used as a safety net.

The start script automatically checks these prerequisites before starting services. If any are missing, the script will exit with clear error messages and instructions.

For detailed setup instructions, see `docs/10-deployment.md` and `docs/11-build-guide.md`.

## Usage

Run this command to start all services before every development session.

**Related Commands**: See [restart.md](restart.md) for clean restart, [error.md](error.md) for diagnostics.

## Implementation

**Windows (PowerShell)**:
```powershell
.\tools\commands\start.ps1
```

**Linux/macOS (Bash)**:
```bash
./tools/commands/start.sh
```

## What It Does

1. Creates logs directory
2. Starts Backend (FastAPI) on port 8000
3. Starts Agent (intelligent_agent)
4. Starts Frontend (Next.js) on port 3000

## Startup Sequence

1. **Load environment configuration** from the root `.env`
2. **Check Redis availability** and try to auto-start a local Redis instance if it is unreachable
3. **Run configuration validation** via `python scripts/validate-env.py`
4. **Run prerequisite validation** via `python tools/commands/validate-prerequisites.py`
5. **Ensure dependencies** by creating venvs and installing backend/agent/frontend requirements when signatures change
6. **Start services** (backend, agent, frontend) through the Python parallel manager
7. **Run health checks** via `tools/commands/health_check.py` (if present) after services report healthy startup

## Expected Output

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- Backend and frontend logs are written to the `logs/` directory; the agent continues to manage its own structured logging internally (no duplicate `logs/agent.log`)

## Prerequisites Check

The start script automatically performs a prerequisites check before starting services:

1. **PostgreSQL Check**: Verifies PostgreSQL is accessible at the host/port specified in `DATABASE_URL`
2. **Redis Check**: Verifies Redis is accessible at the host/port specified in `REDIS_URL`

If prerequisites are not met, the script will:
- Display clear error messages listing missing services
- Provide platform-specific instructions (Windows/Linux/macOS) to start services
- Exit before attempting to start any services

Example output when prerequisites are missing:
```
✗ Prerequisites Check Failed

The following required services are not running:
  • PostgreSQL is not accessible at localhost:5432
  • Redis is not accessible at localhost:6379

To fix this:
[Platform-specific instructions...]
```

## Troubleshooting

### PostgreSQL Not Running

**Error**: `PostgreSQL is not accessible at localhost:5432`

**Solutions**:
- **Windows**: 
  - Check if PostgreSQL service is running: `Get-Service postgresql*`
  - Start service: `net start postgresql-x64-15` (or your specific service name)
  - Or use PowerShell: `Get-Service postgresql* | Start-Service`
- **Linux**: 
  - Check status: `sudo systemctl status postgresql`
  - Start service: `sudo systemctl start postgresql`
- **macOS**: 
  - Check status: `brew services list`
  - Start service: `brew services start postgresql@15`

### Redis Not Running

**Error**: `Redis is not accessible at localhost:6379`

**Solutions**:
- **Windows**: 
  - Check if Redis service is running: `Get-Service redis*`
  - Start service: `net start redis` (if installed as Windows service)
  - Or run manually: `redis-server.exe`
- **Linux**: 
  - Check status: `sudo systemctl status redis`
  - Start service: `sudo systemctl start redis`
- **macOS**: 
  - Check status: `brew services list`
  - Start service: `brew services start redis`

### DATABASE_URL Not Set

**Error**: `DATABASE_URL environment variable not set`

**Solution**: Create a `.env` file in the project root with:
```
DATABASE_URL=postgresql://user:password@localhost:5432/trading_agent
```

### Port Conflicts

If services fail to start due to port conflicts:

- **Backend (port 8000)**: Check if another process is using port 8000
  - Windows: `netstat -ano | findstr :8000`
  - Linux/macOS: `lsof -i :8000`
- **Frontend (port 3000)**: Check if another process is using port 3000
  - Windows: `netstat -ano | findstr :3000`
  - Linux/macOS: `lsof -i :3000`

### Service Starts But Immediately Dies

If a service starts but dies immediately:

1. Check the service log file in `logs/` directory:
   - `logs/backend.log` - Backend errors
   - `logs/agent.log` - Agent errors
   - `logs/frontend.log` - Frontend errors
2. Look for error messages in the logs
3. Common causes:
   - Missing environment variables
   - Database connection issues (even if PostgreSQL is running, check credentials)
   - Port conflicts
   - Missing dependencies

### Frontend Not Accessible

If the frontend appears to start but is not accessible:

1. Check if the backend is running (frontend depends on backend API)
2. Verify `NEXT_PUBLIC_API_URL` is set correctly in frontend environment
3. Check browser console for connection errors
4. Verify backend is accessible at the configured URL

## Notes

- The start script checks prerequisites automatically before starting services
- On both Windows and macOS/Linux, the command attempts to start a local Redis instance automatically if port 6379 is unavailable
- Ensure `logs/` directory exists (created automatically)
- Confirms backend, agent, and frontend are reachable on `localhost` after successful start
- Always bootstrap logging before running commands (see `docs/12-logging.md`)
- Services run in parallel and share the same terminal output with color-coded prefixes

