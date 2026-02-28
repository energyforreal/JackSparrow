# Docker Deployment Guide

Complete guide for deploying JackSparrow Trading Agent using Docker and Docker Compose.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Configuration](#environment-configuration)
- [Building Images](#building-images)
- [Deployment](#deployment)
- [Service Configuration](#service-configuration)
- [Health Checks](#health-checks)
- [Logging](#logging)
- [Volumes and Data Persistence](#volumes-and-data-persistence)
- [Networking](#networking)
- [Production Deployment](#production-deployment)
- [Scaling](#scaling)
- [Backup and Recovery](#backup-and-recovery)
- [Troubleshooting](#troubleshooting)
- [Advanced Topics](#advanced-topics)

---

## Overview

Docker deployment provides a containerized, production-ready solution for running all JackSparrow services. This deployment method ensures:

- **Consistency**: Same environment across development, testing, and production
- **Isolation**: Services run in isolated containers with resource limits
- **Scalability**: Easy to scale services horizontally
- **Portability**: Deploy anywhere Docker runs
- **Security**: Non-root users, network isolation, resource limits
- **Reliability**: Health checks, restart policies, log rotation

---

## Architecture

The Docker deployment uses a multi-container architecture:

```
┌─────────────────────────────────────────────────────────┐
│              Docker Network (jacksparrow-network)       │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Backend  │  │  Agent   │  │ Frontend │             │
│  │ :8000    │  │  :8001   │  │  :3000   │             │
│  │ (FastAPI)│  │ (Python) │  │ (Next.js)│             │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘             │
│       │             │             │                     │
│       └─────────────┴─────────────┘                     │
│                  │                                      │
│       ┌──────────┼──────────┐                          │
│       │          │          │                          │
│  ┌────▼───┐ ┌───▼────┐                                  │
│  │Postgres│ │ Redis  │                                  │
│  │ :5432  │ │ :6379  │                                  │
│  │(Volume)│ │(Volume)│                                  │
│  └────────┘ └────────┘                                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
         │                    │
         │                    │
  ┌──────▼──────┐    ┌───────▼──────┐
  │  Models     │    │    Logs      │
  │  (bind)     │    │   (bind)     │
  └─────────────┘    └──────────────┘
```

**Container Communication:**
- Services communicate via Docker's internal network using service names as hostnames
- External access through exposed ports only
- Isolated network prevents unauthorized access

---

## Prerequisites

### Required Software

- **Docker Engine 24+**: [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose V2**: Included with Docker Desktop or install separately
- **Git**: For cloning repository
- **bash** (Unix/Linux/macOS) or **PowerShell** (Windows): For running deployment scripts

### System Requirements

**Minimum:**
- CPU: 4 cores
- RAM: 8GB
- Disk: 20GB free space

**Recommended (Production):**
- CPU: 8+ cores
- RAM: 16GB+
- Disk: 50GB+ free space (SSD recommended)

### Verify Installation

```bash
# Check Docker version
docker --version
# Should show: Docker version 24.x.x or higher

# Check Docker Compose version
docker compose version
# Should show: Docker Compose version v2.x.x or higher

# Test Docker
docker run hello-world
```

---

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/energyforreal/JackSparrow.git
cd JackSparrow
```

### 2. Create Environment File

```bash
# Copy example template
cp .env.example .env

# Edit with your values
# Required: DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET, 
#           JWT_SECRET_KEY, API_KEY, POSTGRES_PASSWORD
nano .env  # or use your preferred editor
```

### 3. Prepare Directories

```bash
mkdir -p logs/backend logs/agent logs/frontend models
# Optional legacy SQLite file (no longer used by the Docker stack):
# touch kubera_pokisham.db
```

### 4. Build and Deploy

```bash
# Build images
./scripts/docker/build.sh

# Start services
./scripts/docker/deploy.sh up

# Check health
./scripts/docker/healthcheck.sh
```

### 5. Access Services

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Agent Feature Server**: http://localhost:8002

---

## Environment Configuration

### Environment Variables

**Single Root `.env` File**: The `.env` file in the project root is the **single source of truth** for all environment variables. All services (backend, agent, frontend) read from this one file.

**How Docker Compose Loads Environment Variables:**
- **Backend and Agent**: Docker Compose automatically loads the root `.env` file via the `env_file: - .env` directive
- **Frontend**: Receives variables through the `environment:` section in `docker-compose.yml`, which reads from root `.env`
- **Database Services**: Use variables directly from root `.env` via `${VARIABLE_NAME}` syntax

**Setup Instructions:**

1. Copy the example template: `cp .env.example .env`
2. Edit `.env` with your actual values (see `.env.example` for complete template)
3. Required variables: `DELTA_EXCHANGE_API_KEY`, `DELTA_EXCHANGE_API_SECRET`, `JWT_SECRET_KEY`, `API_KEY`, `POSTGRES_PASSWORD`
4. Docker Compose will automatically load this file when you run `docker compose up`

**Required Variables:**

```bash
# Database
POSTGRES_USER=jacksparrow
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=trading_agent
DATABASE_URL=postgresql://jacksparrow:password@postgres:5432/trading_agent

# Delta Exchange API
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret

# Security
JWT_SECRET_KEY=your_jwt_secret
API_KEY=your_api_key
```

**Service Ports:**

```bash
BACKEND_PORT=8000
FRONTEND_PORT=3000
FEATURE_SERVER_PORT=8002
POSTGRES_PORT=5432
REDIS_PORT=6379
```

**Frontend Configuration (Built at Build Time):**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_BACKEND_API_KEY=your_api_key
```

**Important Notes:**
- **No service-specific `.env` files needed**: All services share the same root `.env` file
- **Database URLs in Docker**: Use service names (e.g., `postgres`, `redis`, `agent`) instead of `localhost`
- **For local development**: Database URLs should use `localhost` instead of service names

### Production Environment

For production deployments:

- Use strong, randomly generated secrets (32+ characters, mixed case, numbers, symbols)
- Update frontend URLs to production domain (use `https://` and `wss://`)
- Configure HTTPS endpoints
- Enable log forwarding if needed
- Set appropriate log levels (INFO or WARNING, not DEBUG)
- Ensure `CORS_ORIGINS` only includes production domains

---

## Building Images

### Using Build Scripts (Recommended)

```bash
# Unix/Linux/macOS
./scripts/docker/build.sh [VERSION] [COMMIT_SHA]

# Windows PowerShell
.\scripts\docker\build.ps1 -Version "1.0.0" -CommitSha "abc123"
```

**Options:**
- `VERSION`: Image tag version (default: `latest`)
- `COMMIT_SHA`: Git commit SHA for tagging
- `DOCKER_REGISTRY`: Optional registry for pushing images

### Manual Build

```bash
# Build all services
docker compose build

# Build specific service
docker compose build backend

# Build with no cache
docker compose build --no-cache

# Build with progress output
docker compose build --progress=plain
```

### Image Structure

**Backend (`backend/Dockerfile`):**
- Multi-stage build (builder + runtime)
- Base: `python:3.11-slim`
- Non-root user: `backend`
- Optimized layer caching
- Health check included

**Agent (`agent/Dockerfile`):**
- Multi-stage build (builder + runtime)
- Base: `python:3.11-slim`
- ML dependencies optimized
- Non-root user: `agent`
- Health check included

**Frontend (`frontend/Dockerfile`):**
- Multi-stage build (deps + builder + runtime)
- Base: `node:20-bullseye-slim`
- Production-optimized Next.js build
- Non-root user: `frontend`
- Health check included

---

## Deployment

### Using Deployment Scripts (Recommended)

```bash
# Start all services
./scripts/docker/deploy.sh up

# Stop all services
./scripts/docker/deploy.sh down

# Restart all services
./scripts/docker/deploy.sh restart

# Rolling update
./scripts/docker/deploy.sh update

# View logs
./scripts/docker/deploy.sh logs
```

### Manual Deployment

```bash
# Start services in detached mode
docker compose up -d

# Start with logs visible
docker compose up

# Start specific services
docker compose up -d postgres redis
docker compose up -d backend agent frontend

# Stop services
docker compose down

# Stop and remove volumes (WARNING: deletes data)
docker compose down -v
```

### Service Startup Order

Services start in dependency order:

1. **Infrastructure**: `postgres`, `redis` (health-checked)
2. **Agent**: Waits for `postgres` and `redis` to be healthy
3. **Backend**: Waits for `postgres`, `redis`, and `agent` to be ready
4. **Frontend**: Waits for `backend` to be ready

This ensures services start in the correct order and handle startup gracefully.

---

## Service Configuration

### Resource Limits

All services have resource limits configured:

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
    reservations:
      cpus: '1'
      memory: 1G
```

**Service-Specific Limits:**
- **Postgres**: 2 CPU, 2GB RAM
- **Redis**: 1 CPU, 512MB RAM
- **Agent**: 4 CPU, 4GB RAM (ML workloads)
- **Backend**: 2 CPU, 2GB RAM
- **Frontend**: 1 CPU, 1GB RAM

Adjust limits in `docker-compose.yml` based on your system resources.

### Restart Policies

All services use `restart: unless-stopped`:

- Containers automatically restart on failure
- Containers restart after system reboot
- Manual stops (`docker compose stop`) are not restarted

### Health Checks

Each service has configured health checks:

```yaml
healthcheck:
  test: ["CMD", "health-check-command"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 20s
```

**Health Check Endpoints:**
- **Backend**: `curl http://localhost:8000/api/v1/health`
- **Agent**: `python -m agent.healthcheck`
- **Frontend**: HTTP GET on port 3000
- **Postgres**: `pg_isready`
- **Redis**: `redis-cli ping`

---

## Health Checks

### Using Health Check Script

```bash
# Run comprehensive health check
./scripts/docker/healthcheck.sh
```

The script checks:
- Container health status
- HTTP endpoint availability
- Database connectivity
- Redis connectivity
- Recent errors in logs

### Manual Health Checks

```bash
# Check service status
docker compose ps

# Check specific service health
docker inspect --format='{{.State.Health.Status}}' jacksparrow-backend

# Test backend health endpoint
curl http://localhost:8000/api/v1/health

# Test frontend
curl http://localhost:3000

# Test database connectivity
docker compose exec postgres pg_isready -U jacksparrow

# Test Redis connectivity
docker compose exec redis redis-cli ping
```

---

## Logging

### Log Configuration

All services use JSON file logging driver with rotation:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

**Log Locations:**
- Container logs: `docker compose logs [service]`
- Application logs: `./logs/[service]/` (bind-mounted)

### Viewing Logs

```bash
# Follow all logs
docker compose logs -f

# Follow specific service
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100

# Logs since timestamp
docker compose logs --since 2024-01-01T00:00:00
```

### Log Aggregation

For production, consider:
- **Loki + Grafana**: Log aggregation and visualization
- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Datadog**: Cloud-based log management
- **CloudWatch**: AWS log aggregation

Configure `LOG_FORWARDING_ENABLED=true` and `LOG_FORWARDING_ENDPOINT` in `.env` for log forwarding.

---

## Volumes and Data Persistence

### Volume Types

**Named Volumes (Persistent):**
- `postgres-data`: PostgreSQL database files
- `redis-data`: Redis data and AOF files

**Bind Mounts (Host Directories):**
- `./agent/model_storage` → `/app/agent/model_storage`: Model files
- `./logs/[service]` → `/logs`: Application logs
- `./kubera_pokisham.db` → `/data/kubera_pokisham.db`: Legacy SQLite database

### Backup Volumes

```bash
# Backup PostgreSQL volume
docker run --rm -v jacksparrow_postgres-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres-backup.tar.gz /data

# Backup Redis volume
docker run --rm -v jacksparrow_redis-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/redis-backup.tar.gz /data
```

### Restore Volumes

```bash
# Restore PostgreSQL volume
docker run --rm -v jacksparrow_postgres-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/postgres-backup.tar.gz -C /

# Restore Redis volume
docker run --rm -v jacksparrow_redis-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/redis-backup.tar.gz -C /
```

---

## Networking

### Network Configuration

All services run on isolated Docker network:

```yaml
networks:
  jacksparrow-network:
    driver: bridge
```

**Internal Communication:**
- Services use service names as hostnames (e.g., `postgres`, `redis`, `agent`)
- Internal DNS resolution handled by Docker
- No external access to internal network

**External Access:**
- Ports exposed through host mapping
- Only necessary ports exposed (backend: 8000, frontend: 3000, agent: 8001)

### Custom Network

To use a custom network:

```yaml
networks:
  jacksparrow-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

---

## Production Deployment

### Security Checklist

Before deploying to production:

- [ ] All passwords are strong (32+ characters, mixed case, numbers, symbols)
- [ ] API keys are production keys (not test/paper trading keys)
- [ ] `JWT_SECRET_KEY` is unique and randomly generated
- [ ] `API_KEY` is unique and randomly generated
- [ ] `CORS_ORIGINS` only includes production domains
- [ ] Frontend URLs point to production domain
- [ ] HTTPS/TLS configured (via reverse proxy)
- [ ] Non-root users enabled (already configured)
- [ ] Resource limits set appropriately
- [ ] Health checks configured
- [ ] Log forwarding enabled
- [ ] Backups configured
- [ ] Monitoring and alerting set up

### Reverse Proxy Configuration

Use nginx or traefik for HTTPS termination:

**nginx Example:**

```nginx
upstream backend {
    server localhost:8000;
}

upstream frontend {
    server localhost:3000;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Secrets Management

**Option 1: Docker Secrets (Docker Swarm)**

```yaml
secrets:
  postgres_password:
    external: true

services:
  postgres:
    secrets:
      - postgres_password
```

**Option 2: External Secret Management**

- **AWS Secrets Manager**: For AWS deployments
- **HashiCorp Vault**: Self-hosted secret management
- **Kubernetes Secrets**: For Kubernetes deployments

**Option 3: Environment Variables (Not Recommended for Production)**

Use `.env` file with restricted permissions (`chmod 600 .env`).

---

## Scaling

### Horizontal Scaling

Scale services horizontally:

```bash
# Scale backend (requires load balancer)
docker compose up -d --scale backend=3

# Scale agent (for parallel processing)
docker compose up -d --scale agent=2
```

**Considerations:**
- **Backend**: Requires load balancer (nginx/traefik) for multiple instances
- **Agent**: Can run multiple instances for parallel symbol processing
- **Frontend**: Multiple instances with load balancer
- **Postgres**: Use read replicas for read scaling
- **Redis**: Use Redis Cluster for high availability

### Vertical Scaling

Adjust resource limits in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'  # Increase from 2
      memory: 4G  # Increase from 2G
```

---

## Backup and Recovery

### Automated Backups

Create backup script (`scripts/docker/backup.sh`):

```bash
#!/bin/bash
BACKUP_DIR="./backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup PostgreSQL
docker compose exec -T postgres pg_dump -U jacksparrow trading_agent | \
  gzip > $BACKUP_DIR/postgres_$DATE.sql.gz

# Backup Redis
docker compose exec -T redis redis-cli SAVE
docker cp jacksparrow-redis:/data/dump.rdb $BACKUP_DIR/redis_$DATE.rdb

# Backup volumes
docker run --rm -v jacksparrow_postgres-data:/data -v $(pwd)/$BACKUP_DIR:/backup \
  alpine tar czf /backup/postgres-volume_$DATE.tar.gz /data

echo "Backup completed: $BACKUP_DIR"
```

### Recovery

```bash
# Restore PostgreSQL
gunzip -c backups/postgres_YYYYMMDD_HHMMSS.sql.gz | \
  docker compose exec -T postgres psql -U jacksparrow -d trading_agent

# Restore Redis
docker cp backups/redis_YYYYMMDD_HHMMSS.rdb jacksparrow-redis:/data/dump.rdb
docker compose restart redis
```

---

## Troubleshooting

### Common Issues

#### Port Already in Use

**Problem**: Port conflict when starting services

**Solution**:
```bash
# Check what's using the port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Change port in .env
BACKEND_PORT=8001
```

#### Container Won't Start

**Problem**: Container exits immediately

**Solution**:
```bash
# Check logs
docker compose logs [service]

# Check container status
docker compose ps -a

# Run container interactively
docker compose run --rm backend sh
```

#### Database Connection Errors

**Problem**: Services can't connect to PostgreSQL

**Solution**:
```bash
# Verify database is healthy
docker compose ps postgres

# Check database logs
docker compose logs postgres

# Verify connection string uses service name
# DATABASE_URL=postgresql://user:pass@postgres:5432/db
# NOT: postgresql://user:pass@localhost:5432/db
```

#### Permission Denied Errors

**Problem**: Permission denied when writing to volumes

**Solution**:
```bash
# Fix permissions
sudo chown -R $USER:$USER logs/ models/

# Or run container with user mapping
# Add to docker-compose.yml:
user: "${UID}:${GID}"
```

#### Model Files Not Found

**Problem**: Agent can't find model files

**Solution**:
```bash
# Verify model storage directory is mounted
docker compose exec agent ls -la /app/agent/model_storage

# Check volume mount in docker-compose.yml
# volumes:
#   - ./agent/model_storage:/app/agent/model_storage

# Ensure model files exist
ls -la agent/model_storage/xgboost/
```

### Debugging

**Enable Debug Logging:**
```bash
# Set in .env
LOG_LEVEL=DEBUG
BACKEND_LOG_LEVEL=DEBUG
AGENT_LOG_LEVEL=DEBUG

# Restart services
docker compose restart
```

**Inspect Container:**
```bash
# Enter container
docker compose exec backend sh
docker compose exec agent sh

# Check environment variables
docker compose exec backend env

# Check network connectivity
docker compose exec backend ping postgres
docker compose exec backend ping redis
```

---

## Advanced Topics

### Custom Dockerfile Build Arguments

Add build arguments to Dockerfiles:

```dockerfile
ARG BUILD_DATE
ARG VERSION
ARG COMMIT_SHA

LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.version=$VERSION
LABEL org.opencontainers.image.revision=$COMMIT_SHA
```

### Docker Compose Overrides

Create `docker-compose.override.yml` for local development:

```yaml
version: "3.9"

services:
  backend:
    volumes:
      - ./backend:/app  # Mount source for hot-reload
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    volumes:
      - ./frontend:/app
      - /app/node_modules
      - /app/.next
    command: npm run dev
```

Use with: `docker compose -f docker-compose.yml -f docker-compose.override.yml up`

### Multi-Environment Deployment

Use environment-specific compose files:

```bash
# Development
docker compose -f docker-compose.yml -f docker-compose.dev.yml up

# Production
docker compose -f docker-compose.yml -f docker-compose.prod.yml up
```

### Monitoring Integration

Add Prometheus and Grafana:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

---

## Related Documentation

- [Deployment Documentation](10-deployment.md) - General deployment guide
- [Architecture Documentation](01-architecture.md) - System architecture
- [Build Guide](11-build-guide.md) - Build instructions
- [Logging Documentation](12-logging.md) - Logging setup and configuration

---

**Last Updated**: 2024
**Maintainer**: JackSparrow Development Team

