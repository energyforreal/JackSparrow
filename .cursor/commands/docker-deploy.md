# Docker Deployment

Deploy JackSparrow Trading Agent using Docker Compose.

## Usage

**Related Commands**: See [docker-start.md](docker-start.md) for individual container management, [docker-logs.md](docker-logs.md) for log viewing.

**Production deployment:**
```powershell
.\scripts\docker\deploy.ps1 up
```

```bash
./scripts/docker/deploy.sh up
```

**Development deployment (with hot-reload):**
```powershell
.\scripts\docker\dev-start.ps1
```

```bash
./scripts/docker/dev-start.sh
```

## Implementation

**Windows (PowerShell)**:
```powershell
.\scripts\docker\deploy.ps1 [up|down|restart|update|logs] [-PullImages]
```

**Linux/macOS (Bash)**:
```bash
./scripts/docker/deploy.sh [up|down|restart|update|logs]
```

## Deployment Modes

### Production Mode

Uses `docker-compose.yml` with production Dockerfiles:
- Images built with source code baked in
- Optimized for production performance
- No hot-reload (requires rebuild for changes)

```bash
docker-compose up --build
```

### Development Mode

Uses `docker-compose.dev.yml` override with hot-reload:
- Source code mounted as volumes
- Auto-reload on code changes
- Faster iteration during development

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Deployment Options

- **`up`**: Start all services (default)
- **`down`**: Stop all services
- **`restart`**: Restart all services
- **`update`**: Rolling update (pull images and update services one by one)
- **`logs`**: View logs from all services

## Examples

**Start production environment:**
```powershell
.\scripts\docker\deploy.ps1 up
```

```bash
./scripts/docker/deploy.sh up
```

**Start development environment:**
```powershell
.\scripts\docker\dev-start.ps1 --Build
```

```bash
./scripts/docker/dev-start.sh --build
```

**Update services:**
```powershell
.\scripts\docker\deploy.ps1 update -PullImages
```

```bash
PULL_IMAGES=true ./scripts/docker/deploy.sh update
```

**View logs:**
```powershell
.\scripts\docker\deploy.ps1 logs
```

```bash
./scripts/docker/deploy.sh logs
```

## Health Checks

The deployment script automatically checks service health:
- PostgreSQL: Database connectivity
- Redis: Cache connectivity
- Backend: API health endpoint
- Agent: Agent health check
- Frontend: HTTP response

## Notes

- Ensure `.env` file exists with required environment variables
- Development mode requires rebuilding images on first run: `--Build` flag
- Production mode is optimized for performance and security
- Development mode enables hot-reload for faster iteration
- Always bootstrap logging before running commands (see `docs/12-logging.md`)

