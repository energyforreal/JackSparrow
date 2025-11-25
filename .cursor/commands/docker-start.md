# Start Docker Container

Start individual Docker containers with automatic dependency handling.

## Usage

**Related Commands**: See [docker-deploy.md](docker-deploy.md) for full deployment, [docker-logs.md](docker-logs.md) for log viewing.

```powershell
.\scripts\docker\start-container.ps1 backend
```

```bash
./scripts/docker/start-container.sh backend
```

## Implementation

**Windows (PowerShell)**:
```powershell
.\scripts\docker\start-container.ps1 <container1> [container2] ...
```

**Linux/macOS (Bash)**:
```bash
./scripts/docker/start-container.sh <container1> [container2] ...
```

## Parameters

- **`container`**: One or more container names to start
  - Available containers: `backend`, `agent`, `frontend`, `postgres`, `redis`

## Dependency Handling

The script automatically starts dependencies:
- **backend** → starts `postgres`, `redis`
- **agent** → starts `postgres`, `redis`, `backend`
- **frontend** → starts `backend`
- **postgres** → no dependencies
- **redis** → no dependencies

## Examples

**Start backend (with dependencies):**
```powershell
.\scripts\docker\start-container.ps1 backend
```

```bash
./scripts/docker/start-container.sh backend
```

**Start multiple containers:**
```bash
scripts/docker/start-container.ps1 backend agent
scripts/docker/start-container.sh backend agent frontend
```

**Start agent (automatically starts postgres, redis, backend):**
```bash
scripts/docker/start-container.ps1 agent
```

## Health Checks

After starting each container, the script:
1. Waits for the container to be healthy (up to 60 seconds)
2. Reports health status
3. Continues with next container if health check passes

## Output

- Shows which containers are already running
- Displays dependency startup sequence
- Reports health check status for each container
- Shows final container status summary

## Notes

- Containers already running are skipped
- Dependencies are started automatically
- Health checks ensure services are ready before proceeding
- Use this for targeted container management during development
- For full stack startup, use `scripts/docker/dev-start.ps1` or `scripts/docker/dev-start.sh`

