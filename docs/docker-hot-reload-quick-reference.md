# Docker Hot Reload - Quick Reference

## Quick Commands

### Start Development Environment
```bash
# Unix/Linux/macOS
./scripts/docker/dev-start.sh --build

# Windows PowerShell
.\scripts\docker\dev-start.ps1 -Build

# Manual
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### Stop Services
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

### View Logs
```bash
# All services
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

# Specific service
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f agent
docker-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f frontend
```

### Restart Service
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart agent
```

### Validate Setup
```bash
# Unix/Linux/macOS
./scripts/docker/validate-hot-reload.sh

# Windows PowerShell
.\scripts\docker\validate-hot-reload.ps1
```

## Hot Reload Behavior

| Service | Trigger | Action | Log Message |
|---------|--------|--------|-------------|
| **Backend** | Edit `.py` file in `backend/` | Uvicorn restarts | `Detected file change... Reloading...` |
| **Agent** | Edit `.py` file in `agent/` | Agent process restarts | `agent_file_changed... restarting agent...` |
| **Frontend** | Edit `.tsx/.ts/.css` in `frontend/` | Browser updates (HMR) | Browser console: `[HMR] connected` |

## Troubleshooting Quick Fixes

**Changes not reflecting?**
```bash
# Verify you're using dev compose
docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps

# Check volume mounts
docker-compose -f docker-compose.yml -f docker-compose.dev.yml config | grep volumes
```

**Agent not restarting?**
```bash
# Check watchdog
docker-compose exec agent pip list | grep watchdog

# Restart manually
docker-compose -f docker-compose.yml -f docker-compose.dev.yml restart agent
```

**Frontend not updating?**
- Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS)
- Check browser console for errors
- Check logs: `docker-compose logs -f frontend`

## File Locations

- **Backend code**: `backend/` → mounted to `/app/backend` in container
- **Agent code**: `agent/` → mounted to `/app/agent` in container
- **Frontend code**: `frontend/` → mounted to `/app` in container
- **Logs**: `logs/backend/`, `logs/agent/`, `logs/frontend/`

## See Also

- [Full Hot Reload Guide](docker-hot-reload.md) - Comprehensive documentation
- [Deployment Guide](10-deployment.md) - Complete Docker deployment docs

