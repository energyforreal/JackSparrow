# Docker Hot Reload Guide

## Overview

The JackSparrow project supports hot reload for Docker deployments, allowing code changes to be automatically reflected in running containers without rebuilding Docker images. This significantly speeds up development iteration.

## How It Works

The hot reload system uses Docker volume mounts to sync your local source code with the container filesystem, combined with file watchers and development servers that automatically restart when files change.

### Architecture

**Backend (FastAPI):**
- Uses `uvicorn --reload` flag to watch for Python file changes
- Automatically restarts the FastAPI server when `.py` files are modified
- Volume mount: `./backend:/app/backend:rw`

**Agent (Python):**
- Uses `watchdog` library to monitor Python files for changes
- Automatically restarts the agent process when `.py` files are modified
- Volume mount: `./agent:/app/agent:rw`

**Frontend (Next.js):**
- Uses Next.js built-in Hot Module Replacement (HMR)
- Automatically updates the browser when React/TypeScript files change
- Volume mount: `./frontend:/app:rw` (with `node_modules` and `.next` excluded)

## Quick Start

### Prerequisites

- Docker Engine 20.10+ and Docker Compose 2.0+
- `.env` file configured in project root
- Source code in `backend/`, `agent/`, and `frontend/` directories

### Validate Setup

Before starting, you can validate the hot reload configuration:

```bash
# Unix/Linux/macOS
./scripts/docker/validate-hot-reload.sh

# Windows PowerShell
.\scripts\docker\validate-hot-reload.ps1
```

This checks that all required files, volume mounts, and configurations are in place.

### Starting Development Environment

**Using Helper Scripts (Recommended):**

```bash
# Unix/Linux/macOS
./scripts/docker/dev-start.sh --build

# Windows PowerShell
.\scripts\docker\dev-start.ps1 -Build
```

**Manual Docker Compose:**

```bash
# First time (builds images)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Subsequent starts (uses cached images)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**Detached Mode (Background):**

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Stopping Services

```bash
# Stop all services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down

# Stop and remove volumes (WARNING: deletes data)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

## Usage Examples

### Making Code Changes

1. **Backend Changes:**
   ```bash
   # Edit any Python file in backend/
   vim backend/api/routes/trades.py
   
   # Save the file - uvicorn will automatically reload
   # Check logs to see reload confirmation
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
   ```

2. **Agent Changes:**
   ```bash
   # Edit any Python file in agent/
   vim agent/core/intelligent_agent.py
   
   # Save the file - watchdog will restart the agent
   # Check logs to see restart confirmation
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f agent
   ```

3. **Frontend Changes:**
   ```bash
   # Edit any React/TypeScript file in frontend/
   vim frontend/components/Dashboard.tsx
   
   # Save the file - Next.js HMR will update the browser automatically
   # No container restart needed for frontend changes
   ```

### Viewing Logs

```bash
# All services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

# Specific service
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f agent
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f frontend

# Last 100 lines
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs --tail=100 backend
```

### Restarting a Specific Service

```bash
# Restart backend only
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart backend

# Restart agent only
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart agent
```

## Development vs Production

### Development Mode (`docker-compose.dev.yml`)

**Characteristics:**
- ✅ Hot reload enabled
- ✅ Source code mounted as volumes
- ✅ Faster iteration (no rebuild needed)
- ✅ Development dependencies included
- ✅ Debug logging enabled
- ⚠️ Not optimized for production performance
- ⚠️ Larger container images

**When to Use:**
- Active development and debugging
- Testing code changes quickly
- Local development environment

### Production Mode (`docker-compose.yml`)

**Characteristics:**
- ✅ Optimized builds (multi-stage)
- ✅ Source code baked into images
- ✅ Production dependencies only
- ✅ Better security and performance
- ✅ Smaller container images
- ⚠️ Requires rebuild for code changes

**When to Use:**
- Production deployments
- Performance testing
- CI/CD pipelines
- Staging environments

## File Watching Details

### Backend (Uvicorn)

Uvicorn's `--reload` flag watches for changes in:
- All `.py` files in the mounted `backend/` directory
- Automatically restarts the FastAPI server
- Reload delay: ~1-2 seconds

**Reload Detection:**
```bash
# You'll see this in logs when reload happens:
INFO:     Detected file change in 'backend/api/routes/trades.py'. Reloading...
INFO:     Application startup complete.
```

### Agent (Watchdog)

The agent uses a custom file watcher (`agent/scripts/dev_watcher.py`) that:
- Monitors `/app/agent` directory recursively
- Watches for `.py` file changes
- Debounces rapid file changes (1 second delay)
- Gracefully restarts the agent process

**Restart Detection:**
```bash
# You'll see this in logs when restart happens:
INFO: agent_file_changed file=agent/core/intelligent_agent.py message="Python file changed, restarting agent..."
INFO: agent_stopping message="Stopping existing agent process for restart"
INFO: agent_starting message="Starting agent process"
```

### Frontend (Next.js HMR)

Next.js Hot Module Replacement:
- Updates React components without full page reload
- Preserves component state when possible
- Updates CSS/styles instantly
- Shows compilation errors in browser

**HMR Detection:**
- Browser console shows: `[HMR] connected`
- Changes appear instantly in browser
- No container restart needed

## Troubleshooting

### Code Changes Not Reflecting

**Problem:** Changes to files aren't being picked up

**Solutions:**
1. Verify you're using the dev compose file:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps
   ```

2. Check volume mounts:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml config | grep volumes
   ```

3. Verify file permissions:
   ```bash
   # Files should be readable by container user
   ls -la backend/
   ```

4. Check if files are being watched:
   ```bash
   # Backend - should see reload messages
   docker-compose logs -f backend | grep -i reload
   
   # Agent - should see file change messages
   docker-compose logs -f agent | grep -i "file_changed"
   ```

### Agent Not Restarting

**Problem:** Agent doesn't restart on file changes

**Solutions:**
1. Verify watchdog is installed:
   ```bash
   docker-compose exec agent pip list | grep watchdog
   ```

2. Check agent watcher logs:
   ```bash
   docker-compose logs -f agent | grep -i watcher
   ```

3. Verify file watcher script exists:
   ```bash
   docker-compose exec agent ls -la /app/agent/scripts/dev_watcher.py
   ```

4. Manually restart agent:
   ```bash
   docker-compose restart agent
   ```

### Frontend Not Updating

**Problem:** Browser doesn't show changes

**Solutions:**
1. Check Next.js dev server is running:
   ```bash
   docker-compose logs frontend | grep -i "ready"
   ```

2. Verify HMR is connected (check browser console)

3. Hard refresh browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS)

4. Check for compilation errors:
   ```bash
   docker-compose logs -f frontend
   ```

### Permission Errors

**Problem:** Permission denied errors when writing files

**Solutions:**
1. Fix file permissions:
   ```bash
   sudo chown -R $USER:$USER backend/ agent/ frontend/
   ```

2. Check container user:
   ```bash
   docker-compose exec backend whoami
   docker-compose exec agent whoami
   ```

3. Run containers with user mapping (if needed):
   ```yaml
   # Add to docker-compose.dev.yml
   user: "${UID}:${GID}"
   ```

### Performance Issues

**Problem:** Development mode is slow

**Solutions:**
1. Development mode is intentionally slower than production
2. Use production mode for performance testing
3. Exclude large directories from volumes:
   ```yaml
   volumes:
     - ./backend:/app/backend:rw
     - /app/backend/__pycache__  # Exclude cache
   ```

4. Use `.dockerignore` to exclude unnecessary files

### Port Conflicts

**Problem:** Port already in use

**Solutions:**
1. Check what's using the port:
   ```bash
   # Unix/Linux/macOS
   lsof -i :8000
   
   # Windows
   netstat -ano | findstr :8000
   ```

2. Change port in `.env`:
   ```bash
   BACKEND_PORT=8001
   FRONTEND_PORT=3001
   ```

## Best Practices

1. **Use Development Mode for Active Coding**
   - Faster iteration cycle
   - Immediate feedback on changes
   - Better debugging experience

2. **Use Production Mode for Testing**
   - Test actual production behavior
   - Verify optimized builds work
   - Performance benchmarking

3. **Monitor Logs Regularly**
   - Watch for reload/restart messages
   - Catch errors early
   - Verify changes are applied

4. **Keep Dependencies Updated**
   - Rebuild images when dependencies change
   - Use `--build` flag after `requirements.txt` updates

5. **Use .dockerignore**
   - Exclude unnecessary files from builds
   - Faster build times
   - Smaller context size

## Related Documentation

- [Quick Reference](docker-hot-reload-quick-reference.md) - Command cheat sheet
- [Deployment Guide](10-deployment.md) - Complete Docker deployment documentation
- [Build Guide](11-build-guide.md) - Project build and development commands
- [Debugging Guide](13-debugging.md) - Debugging tips and techniques

## Summary

Hot reload in Docker enables rapid development iteration by automatically applying code changes without manual rebuilds. The system uses:

- **Backend**: Uvicorn `--reload` for automatic server restarts
- **Agent**: Custom watchdog-based file watcher for process restarts
- **Frontend**: Next.js HMR for instant browser updates

Use development mode (`docker-compose.dev.yml`) for active coding and production mode (`docker-compose.yml`) for final testing and deployment.

