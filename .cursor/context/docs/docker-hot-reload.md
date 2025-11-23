# Docker Hot-Reload Development Guide

This guide explains the Docker hot-reload development workflow for the JackSparrow Trading Agent project.

## Overview

The hot-reload development setup enables real-time code changes without rebuilding Docker images, significantly speeding up the development and debugging process.

## Architecture

### Development Dockerfiles

Development Dockerfiles (`Dockerfile.dev`) differ from production Dockerfiles:

- **Install dependencies only**: No `COPY` of source code
- **Optimized for development**: Includes dev dependencies
- **Volume-mounted code**: Source code mounted at runtime

**Files:**
- `backend/Dockerfile.dev`
- `agent/Dockerfile.dev`
- `frontend/Dockerfile.dev`

### Docker Compose Override

`docker-compose.dev.yml` extends `docker-compose.yml`:

- **Volume mounts**: Source directories mounted into containers
- **Command overrides**: Development commands with hot-reload flags
- **Environment variables**: Development-specific settings

## How Hot-Reload Works

### Backend (FastAPI)

- Uses `uvicorn --reload` flag
- Watches Python files (`.py`) for changes
- Automatically restarts server on file save
- Preserves application state where possible

**Command:**
```bash
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend (Next.js)

- Uses `npm run dev` (Next.js development server)
- Hot Module Replacement (HMR) for React components
- Fast Refresh for instant UI updates
- No full page reload for most changes

**Command:**
```bash
npm run dev
```

### Agent (Python)

- Python module reloads on `.py` file changes
- Some state may be preserved depending on implementation
- Watchdog patterns can be added for more control

**Command:**
```bash
python -m agent.core.intelligent_agent
```

## Volume Mounts

### Backend
```
./backend:/app/backend:rw
```
- Source code mounted read-write
- Changes immediately visible in container
- Python bytecode (`__pycache__`) excluded via `.dockerignore`

### Agent
```
./agent:/app/agent:rw
```
- Source code mounted read-write
- Models directory mounted separately (read-only)
- Logs directory mounted for persistence

### Frontend
```
./frontend:/app:rw
/app/node_modules        # Anonymous volume (excluded)
/app/.next              # Anonymous volume (excluded)
```
- Source code mounted read-write
- `node_modules` excluded to avoid conflicts
- `.next` build directory excluded for dev server

## Usage

### Starting Development Environment

**First time (build images):**
```bash
make docker-dev
# or
scripts/docker/dev-start.ps1 --Build
scripts/docker/dev-start.sh --build
```

**Subsequent starts:**
```bash
make docker-dev
# or
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Making Code Changes

1. Edit files in your local editor
2. Save the file
3. Changes are automatically detected:
   - **Backend**: Server restarts (watch console)
   - **Frontend**: Browser refreshes/updates
   - **Agent**: Module reloads

### Viewing Logs

```bash
# All services
make docker-logs

# Specific service
make docker-logs SERVICE=backend

# Filter by level
make docker-logs SERVICE=backend LEVEL=ERROR

# Follow logs
scripts/docker/logs.ps1 backend -Follow
```

## Limitations and Considerations

### Performance

- **Slower than production**: Volume mounts add overhead
- **File watching**: Uses system resources for file monitoring
- **Not for load testing**: Use production mode for performance tests

### File Permissions

- Ensure Docker has access to mounted directories
- On Windows: Share drives with Docker Desktop
- On Linux/macOS: Check directory permissions

### Dependencies

- **Python dependencies**: Installed in image, not mounted
- **Node modules**: Excluded from mount (use anonymous volume)
- **System packages**: Installed in image

### State Management

- **Database**: Persistent via Docker volumes
- **Redis**: Persistent via Docker volumes
- **Application state**: May reset on reload (backend/agent)

## Troubleshooting

### Changes Not Reflecting

1. **Verify volume mounts:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml config
   ```

2. **Check file permissions:**
   ```bash
   ls -la backend/
   ```

3. **Restart containers:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
   ```

### Build Issues

1. **Rebuild images:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache
   ```

2. **Check Dockerfile.dev syntax:**
   ```bash
   docker build -f backend/Dockerfile.dev -t test-backend .
   ```

### Port Conflicts

1. **Check if ports are in use:**
   ```bash
   # Windows
   netstat -an | findstr 8000
   
   # Linux/macOS
   lsof -i :8000
   ```

2. **Modify ports in `.env`:**
   ```bash
   BACKEND_PORT=8001
   FRONTEND_PORT=3001
   ```

## Best Practices

1. **Use development mode** for active coding
2. **Use production mode** for final testing
3. **Rebuild images** when dependencies change
4. **Monitor logs** for errors during development
5. **Run audits** before committing changes
6. **Keep `.env` updated** with correct configuration

## Comparison: Development vs Production

| Feature | Development | Production |
|---------|------------|------------|
| Hot-reload | ✅ Enabled | ❌ Disabled |
| Build time | Fast (cached) | Slower (full build) |
| Code changes | Instant | Requires rebuild |
| Performance | Lower | Higher |
| Dependencies | All (dev + prod) | Production only |
| Source code | Volume mount | Baked into image |
| Debugging | Easy | Requires logs |

## Related Commands

- `make docker-dev` - Start development environment
- `make docker-logs` - View container logs
- `make docker-start` - Start specific container
- `make docker-audit` - Audit container errors
- `make docker-stop` - Stop all containers

## Additional Resources

- [Deployment Documentation](../docs/10-deployment.md) - Full deployment guide
- [Docker Commands](../commands/docker-deploy.md) - Docker command reference
- [Build Guide](../docs/11-build-guide.md) - Build instructions
- [Debugging Guide](../docs/13-debugging.md) - Debugging tips

