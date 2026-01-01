# Deployment Documentation

## Overview

This document provides comprehensive instructions for setting up development and testing environments for local runtime execution, environment variables configuration, and troubleshooting guides for the JackSparrow project.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Development Environment Setup](#development-environment-setup)
- [Testing Environment Setup](#testing-environment-setup)
- [Next.js Webapp Development](#nextjs-webapp-development)
- [Environment Variables Reference](#environment-variables-reference)
- [Start the Stack](#start-the-stack)
- [Logging Setup](#logging-setup)
- [Monitoring Setup (Optional)](#monitoring-setup-optional)
- [Operations & Maintenance Commands](#operations--maintenance-commands)
- [Troubleshooting](#troubleshooting)
- [Production Deployment Considerations](#production-deployment-considerations)
- [Related Documentation](#related-documentation)

---

## Development Environment Setup

### Prerequisites

**Required Software**:
- Python 3.11 or higher
- Node.js 18+ and npm
- PostgreSQL 15+ with TimescaleDB extension
- Redis 7.0+
- Git

**Optional Software**:
- Qdrant or Pinecone account (for vector storage)
- Prometheus and Grafana (for monitoring)
- Sentry (for error tracking - optional)
- Celery (for background tasks - optional, not required for local runtime)

> **Note**  
> Optional tooling is not required for the core paper-trading experience. Enable them when you need the corresponding capability (for example, Prometheus/Grafana for observability dashboards or Celery for heavy asynchronous jobs in staging).

---

### Step 1: Clone Repository

```bash
git clone https://github.com/energyforreal/JackSparrow
cd JackSparrow
```

---

### Step 2: Backend Setup

**Create Virtual Environment**:
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Install Dependencies**:
```bash
pip install -r requirements.txt
```

**Required Backend Dependencies**:
- fastapi==0.104.0
- uvicorn==0.24.0
- sqlalchemy==2.0.23
- psycopg2-binary==2.9.9
- redis==5.0.0
- pydantic==2.5.0
- python-dotenv==1.0.0

---

### Step 3: Agent Setup

**Create Virtual Environment**:
```bash
cd agent
python -m venv venv
source venv/bin/activate
```

**Install Dependencies**:
```bash
pip install -r requirements.txt
```

**Required Agent Dependencies**:
- xgboost==2.0.2
- lightgbm==4.0.0
- tensorflow==2.14.0
- scikit-learn==1.3.0
- shap==0.43.0
- qdrant-client==1.6.0
- sentence-transformers==2.2.0
- numpy==1.24.0
- pandas==2.0.0

---

### Step 4: Frontend Setup

**Install Dependencies**:
```bash
cd frontend
npm install
```

**Required Frontend Dependencies**:
- next==14.0.0
- react==18.2.0
- typescript==5.2.0
- tailwindcss==3.3.0
- recharts==2.8.0

---

### Step 5: Database Setup

**Install PostgreSQL with TimescaleDB**:

**Ubuntu/Debian**:
```bash
sudo apt update
sudo apt install postgresql-15 postgresql-contrib
# Install TimescaleDB extension
sudo apt install timescaledb-2-postgresql-15
```

**macOS**:
```bash
brew install postgresql@15
brew install timescaledb
```

**Create Database**:
```bash
createdb trading_agent
psql trading_agent -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

**Run Database Setup**:
```bash
cd scripts
python setup_db.py
```

This script will:
- Enable TimescaleDB extension
- Create PostgreSQL ENUM types (tradeside, tradestatus, ordertype, positionstatus, signaltype)
- Create all required tables (trades, positions, decisions, performance_metrics, model_performance)
- Convert time-series tables to hypertables for optimal performance
- Create necessary indexes

**Note**: For new installations, the setup script automatically creates ENUM types. For existing databases created with older versions, you need to run the migration script (see below).

---

#### Database Migration (Existing Databases Only)

If you have an existing database created with an older version of the setup script (before ENUM types were introduced), you need to migrate your database schema:

**⚠️ Important**: Always backup your database before running migrations in production.

```bash
# From project root directory
python scripts/migrate_enums.py
```

This migration script will:
- Create PostgreSQL ENUM types for all enum columns
- Convert existing VARCHAR columns to ENUM types:
  - `trades.side`, `trades.order_type`, `trades.status`
  - `positions.side`, `positions.status` (fixes portfolio service errors)
  - `decisions.signal`
- Preserve all existing data during migration
- Use database transactions for safe rollback on errors

**Verification**:
After running the migration, restart your backend service and verify:
1. Portfolio service queries work correctly (no enum type errors)
2. Check backend logs for any remaining errors
3. Test the `/api/v1/portfolio/summary` endpoint

**Troubleshooting Migration**:
- If migration fails, the transaction will be rolled back automatically
- Ensure PostgreSQL is running: `pg_isready`
- Verify DATABASE_URL in the root `.env` file is correct
- Check that all enum values in your data match the ENUM type definitions

---

### Step 6: Redis Setup

**Install Redis**:

**Ubuntu/Debian**:
```bash
sudo apt install redis-server
sudo systemctl start redis
```

**macOS**:
```bash
brew install redis
brew services start redis
```

**Verify Installation**:
```bash
redis-cli ping
# Should return: PONG
```

---

### Step 7: Vector Database Setup (Optional)

**Qdrant (Local Installation)**:

**Ubuntu/Debian**:
```bash
# Download and run Qdrant binary
wget https://github.com/qdrant/qdrant/releases/download/v1.7.0/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
./qdrant
```

**macOS**:
```bash
brew install qdrant
qdrant
```

**Windows**:
- Download Qdrant binary from https://github.com/qdrant/qdrant/releases
- Extract and run `qdrant.exe`

**Or use Qdrant Cloud**:
- Sign up at https://cloud.qdrant.io
- Create cluster
- Get API key and URL

**Verify Qdrant Installation**:
```bash
curl http://localhost:6333/health
# Should return: {"status":"ok"}
```

---

### Step 8: Environment Variables

**Single Root `.env` File**: All services (backend, agent, frontend) read from a **single root `.env` file** in the project root directory. This is the only environment file you need to configure.

**Setup Instructions:**

1. Copy the example template: `cp .env.example .env`
2. Edit `.env` with your actual values
3. Fill in all **REQUIRED** variables (marked in `.env.example`)
4. Optionally configure **OPTIONAL** variables as needed

**How Components Read the Root `.env` File:**

- **Backend**: Reads via `ROOT_ENV_PATH` in `backend/core/config.py` (points to root `.env`)
- **Agent**: Reads via `ROOT_ENV_PATH` in `agent/core/config.py` (points to root `.env`)
- **Frontend**: Reads via `loadRootEnv()` function in `frontend/next.config.js` (reads `../.env`)
- **Docker**: Docker Compose automatically loads root `.env` via `env_file: - .env` directive

**Important Notes:**

- **No service-specific `.env` files needed**: All services share the same root `.env` file
- **For local development**: Database URLs should use `localhost` (e.g., `postgresql://user:pass@localhost:5432/db`)
- **For Docker deployments**: Database URLs should use service names (e.g., `postgresql://user:pass@postgres:5432/db`)
- See `.env.example` in the project root for a complete template with all available variables

**Required Variables (Minimum Setup):**

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://user:password@localhost:5432/trading_agent

# Delta Exchange API (REQUIRED)
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret

# Security (REQUIRED)
JWT_SECRET_KEY=your_jwt_secret_key
API_KEY=your_api_key

# Frontend (REQUIRED)
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

**See `.env.example` for the complete list of all available environment variables**, including:
- Database and Redis configuration
- Backend settings (ports, CORS, logging, rate limiting)
- Agent configuration (model paths, trading settings, risk management)
- Frontend Next.js public variables
- Telegram notifications (optional)
- Vector database (Qdrant, optional)
- Docker service ports

> **Template Format Reminder**  
> The root `.env.example` is already organized into sections (Infrastructure & Shared Services, Delta Exchange Credentials, Backend Security & API, Agent Configuration with Risk Management/Trading Session defaults, Frontend, and Optional Services). Copy it verbatim to `.env` and only change the values so every service reads the same structured configuration.

> **Agent Risk Controls**  
> Beyond the core limits (`MAX_POSITION_SIZE`, `MAX_PORTFOLIO_HEAT`, `STOP_LOSS_PERCENTAGE`, `TAKE_PROFIT_PERCENTAGE`), the template exposes additional safeguards such as `MAX_DAILY_LOSS`, `MAX_DRAWDOWN`, `MAX_CONSECUTIVE_LOSSES`, and `MIN_TIME_BETWEEN_TRADES`, plus trading defaults like `INITIAL_BALANCE`, `TRADING_MODE`, `MIN_CONFIDENCE_THRESHOLD`, `UPDATE_INTERVAL`, and `TIMEFRAMES`. Tune these in `.env` to match your testing needs.

---

### Step 9: Start Services

**Recommended (Parallel Startup)**:
```bash
python tools/commands/start_parallel.py
# or use shell scripts:
# Linux/macOS: ./tools/commands/start.sh
# Windows: .\tools\commands\start.ps1
```

The startup system uses a Python-based parallel process manager that performs a comprehensive startup sequence:

#### Startup Sequence

The `start_parallel.py` script executes a 4-step validation and startup process:

1. **Environment Loading**: Loads and validates the root `.env` configuration file
2. **Paper Trading Validation**: Verifies safe paper trading mode (blocks live trading startup)
3. **Redis Availability**: Checks Redis service and attempts auto-startup if available
4. **Configuration Validation**: Runs comprehensive validation including:
   - Environment variables (`validate-env.py`)
   - System prerequisites (Python, Node.js, PostgreSQL, Redis)
   - Optional ML model validation
5. **Service Dependencies**: Ensures all virtual environments and dependencies are set up
6. **Parallel Startup**: Launches backend, agent, and frontend services simultaneously
7. **Health Checks**: Performs post-startup HTTP health verification
8. **Monitoring Dashboard**: Activates real-time monitoring with data freshness tracking

**Key Benefits of Parallel Startup:**
- **Faster initialization**: All services start simultaneously instead of sequentially
- **Real-time log streaming**: Color-coded logs from all services in a single console
- **Cross-platform**: Single Python script works on Windows, macOS, and Linux
- **Built-in validation**: Automatic configuration and prerequisite validation
- **Safety mechanisms**: Paper trading validation prevents accidental live trading
- **Health monitoring**: Automatic health checks and monitoring dashboard
- **Comprehensive error handling**: Clear error messages with troubleshooting guidance

Each service logs to `logs/{service}.log` while also streaming to the console with service name prefixes. The command automatically sets up virtual environments and installs dependencies if needed.

**Manual alternative** (if you prefer separate terminals):

1. **Backend**
   ```bash
   cd backend
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   uvicorn api.main:app --reload --port 8000
   ```

2. **Agent**
   ```bash
   cd agent
   source venv/bin/activate
   python -m agent.core.intelligent_agent
   ```

3. **Frontend**
   ```bash
   cd frontend
   npm run dev
   ```

**Access Dashboard**:
- Frontend Webapp: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

**Note**: The frontend is a Next.js webapp that runs in development mode. For production builds, see the [Build Guide](11-build-guide.md) and refer to the startup scripts + `npm run build` combination described there.

---

## Docker Compose Deployment

Use Docker when you need repeatable 24/7 runtimes or remote deployments. The Docker deployment includes production-ready configurations, optimized multi-stage builds, non-root users, resource limits, and health checks.

For comprehensive Docker deployment documentation, see [Docker Deployment Guide](DOCKER_DEPLOYMENT.md).

### Prerequisites

- **Docker Engine 24+** ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose V2** (`docker compose` CLI)
- **Environment Configuration**: Create `.env` file from `.env.example` with:
  - `DELTA_EXCHANGE_API_KEY`, `DELTA_EXCHANGE_API_SECRET`
  - `JWT_SECRET_KEY`, `API_KEY`
  - `POSTGRES_PASSWORD` (and optionally `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PORT`)

### Quick Start

**1. Prepare persistent assets:**
```bash
mkdir -p logs/backend logs/agent logs/frontend models
touch kubera_pokisham.db
```

**2. Create environment file:**
```bash
# Copy the example template
cp .env.example .env

# Edit .env with your configuration
# Required: DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET, JWT_SECRET_KEY, API_KEY, POSTGRES_PASSWORD
```

**3. Build and start services:**
```bash
# Using deployment scripts (recommended)
./scripts/docker/build.sh
./scripts/docker/deploy.sh up

# Or using docker-compose directly
docker compose up --build -d
```

**4. Verify deployment:**
```bash
# Check service health
./scripts/docker/healthcheck.sh

# Or manually
docker compose ps
docker compose logs -f
```

### Service Architecture

| Service   | Image/Build                     | Port | Resource Limits | Notes |
|-----------|---------------------------------|------|-----------------|-------|
| postgres  | `timescale/timescaledb:2.13.1-pg15` | 5432 | 2 CPU, 2GB RAM | Health-checked, persistent volume |
| redis     | `redis:7.2-alpine`              | 6379 | 1 CPU, 512MB RAM | Append-only mode, persistent volume |
| agent     | `agent/Dockerfile`              | 8001 | 4 CPU, 4GB RAM | Multi-stage build, ML-optimized |
| backend   | `backend/Dockerfile`            | 8000 | 2 CPU, 2GB RAM | Multi-stage build, non-root user |
| frontend  | `frontend/Dockerfile`           | 3000 | 1 CPU, 1GB RAM | Multi-stage build, production-ready |

### Key Features

**Production-Ready Configuration:**
- Multi-stage Dockerfile builds for smaller images
- Non-root users for enhanced security
- Resource limits to prevent resource exhaustion
- Health checks for automatic container management
- Restart policies (`unless-stopped`) for automatic recovery
- Log rotation (10MB max size, 3 files retention)

**Volume Management:**
- `./agent/model_storage` → `/app/agent/model_storage` (bind-mounted for agent model access)
- `./logs/<service>` → `/logs` (structured logs from each container)
- `./kubera_pokisham.db` → `/data/kubera_pokisham.db` (legacy SQLite support)
- `postgres-data` volume (TimescaleDB persistent storage)
- `redis-data` volume (Redis persistent storage)

**Network Isolation:**
- All services communicate on isolated Docker network (`jacksparrow-network`)
- Internal DNS resolution using service names (e.g., `postgres`, `redis`, `agent`)

### Deployment Scripts

The project includes deployment scripts in `scripts/docker/`:

**Build Scripts:**
```bash
# Unix/Linux/macOS
./scripts/docker/build.sh [VERSION] [COMMIT_SHA]

# Windows PowerShell
.\scripts\docker\build.ps1 -Version "1.0.0" -CommitSha "abc123"
```

**Deploy Scripts:**
```bash
# Start services
./scripts/docker/deploy.sh up

# Stop services
./scripts/docker/deploy.sh down

# Restart services
./scripts/docker/deploy.sh restart

# Rolling update
./scripts/docker/deploy.sh update

# View logs
./scripts/docker/deploy.sh logs
```

**Health Check Script:**
```bash
# Check all services
./scripts/docker/healthcheck.sh
```

### Common Operations

**View logs:**
```bash
docker compose logs -f [service]  # Follow logs for specific service
docker compose logs --tail=100    # Last 100 lines from all services
```

**Execute commands in containers:**
```bash
# Run database migrations
docker compose exec backend python scripts/setup_db.py

# Access PostgreSQL
docker compose exec postgres psql -U jacksparrow -d trading_agent

# Access Redis CLI
docker compose exec redis redis-cli
```

**Shutdown & teardown:**
```bash
# Stop containers (keep volumes)
docker compose down

# Stop and remove volumes (WARNING: deletes data)
docker compose down -v

# Stop specific service
docker compose stop backend
```

### Troubleshooting

See [Docker Deployment Guide](DOCKER_DEPLOYMENT.md#troubleshooting) for comprehensive troubleshooting steps.

**Common Issues:**
- **Port conflicts**: Update port in `.env` file (e.g., `BACKEND_PORT=8001`)
- **Volume permissions**: Fix with `sudo chown -R $USER:$USER logs/ models/`
- **Database connection**: Verify `DATABASE_URL` uses service name `postgres`, not `localhost`
- **Health checks failing**: Check logs with `docker compose logs [service]`

### Production Deployment

For production deployments, see [Docker Deployment Guide](DOCKER_DEPLOYMENT.md#production-deployment) for:
- Security hardening checklist
- Secrets management
- HTTPS/TLS configuration
- Backup strategies
- Monitoring and alerting
- Scaling considerations

---

## CI/CD Automation

The workflow defined in `.github/workflows/cicd.yml` enforces quality gates and automates deployments:

### Validation in CI/CD

The CI/CD pipeline includes a validation job that runs before tests:

**Validation Job**:
- Validates environment variable structure (checks .env format, not actual values)
- Validates Python and Node.js versions
- Checks code structure and imports
- Runs before Python and Frontend test jobs

**Validation Steps**:
1. Environment variable validation (structure check)
2. Prerequisites validation (version checks only, services not available in CI)
3. Code quality checks (linting, formatting)

**Note**: Full validation (including service connectivity) requires a local environment with running services. CI validation focuses on code structure and configuration format validation.

### CI/CD Pipeline Steps

1. **Tests** – Backend and agent pytest suites run in parallel via a matrix; the frontend executes `npm test -- --ci`.
2. **Images** – After tests pass, Docker images for `backend`, `agent`, and `frontend` are built with Buildx. Images are tagged with the commit SHA and `latest` and pushed to GitHub Container Registry (GHCR) on the `main` branch.
3. **Deploy** – On `main`, the workflow connects to the deployment host via SSH, pulls the latest repository state, fetches new images, and runs `docker compose up -d --pull always --build` to restart services with zero manual steps.

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Public hostname or IP of the target server |
| `DEPLOY_USER` | SSH user with rights to pull the repo and run Docker |
| `DEPLOY_KEY`  | Private key (PEM) for the deploy user |
| `DEPLOY_PATH` | Absolute path on the server that contains the repository |

The workflow already uses the built-in `GITHUB_TOKEN` for GHCR authentication; no additional registry secret is needed. Ensure the remote server has Docker/Compose installed and that the repository at `DEPLOY_PATH` contains the latest `docker-compose.yml`.

---

## Testing Environment Setup

### Test Database

**Create Test Database**:
```bash
createdb trading_agent_test
psql trading_agent_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
```

**Test Environment Variables**:
```bash
DATABASE_URL=postgresql://user:password@localhost:5432/trading_agent_test
REDIS_URL=redis://localhost:6379/1  # Use different DB
```

---

### Running Tests

**Backend Tests**:
```bash
cd backend
pytest tests/unit/backend/
pytest tests/integration/
```

**Agent Tests**:
```bash
cd agent
pytest tests/unit/agent/
```

**Frontend Tests**:
```bash
cd frontend
npm test
```

**End-to-End Tests**:
```bash
pytest tests/e2e/
```

---

## Next.js Webapp Development

### Development Mode

The frontend runs as a Next.js webapp in development mode:

```bash
cd frontend
npm run dev
```

This starts the Next.js development server with hot-reload enabled. The webapp will be available at `http://localhost:3000`.

### Production Build

To build the frontend for production:

```bash
cd frontend
npm run build
npm start
```

This creates an optimized production build and starts the production server.

### Environment Configuration

The frontend uses environment variables prefixed with `NEXT_PUBLIC_` to expose configuration to the browser. These are configured in the **root `.env` file**:

**Root `.env`** (all environments):
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

**For production**:
```bash
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com/ws
```

### Webapp Features

- Real-time dashboard with WebSocket updates
- Agent status monitoring
- Portfolio visualization
- Trading signal display
- Reasoning chain viewer
- Performance charts and metrics

---

## Environment Variables Reference

### Backend Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes | - |
| `REDIS_URL` | Redis connection string | Yes | - |
| `DELTA_EXCHANGE_API_KEY` | Delta Exchange API key | Yes | - |
| `DELTA_EXCHANGE_API_SECRET` | Delta Exchange API secret | Yes | - |
| `DELTA_EXCHANGE_BASE_URL` | Delta Exchange API base URL | Yes | https://api.india.delta.exchange |
| `QDRANT_URL` | Qdrant vector database URL | No | http://localhost:6333 |
| `QDRANT_API_KEY` | Qdrant API key | No | - |
| `JWT_SECRET_KEY` | JWT secret for authentication | Yes | - |
| `API_KEY` | API key for client authentication | Yes | - |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No | INFO |
| `LOG_DIR` | Backend log directory | No | `./logs/backend` |
| `LOG_RETENTION_DAYS` | Days to retain backend logs | No | 7 |
| `LOG_ARCHIVE_MODE` | `archive` or `delete` previous logs on startup | No | archive |
| `LOG_SESSION_ID` | Optional override for generated session ID | No | - |
| `LOG_FORWARDING_ENABLED` | Toggle remote log forwarding | No | false |
| `LOG_FORWARDING_ENDPOINT` | Remote logging endpoint | No | - |
| `LOG_INCLUDE_STACKTRACE` | Include stack traces in production logs | No | false |
| `FEATURE_SERVER_URL` | MCP Feature Server URL | No | http://localhost:8001 |

### Agent Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes | - |
| `REDIS_URL` | Redis connection string | Yes | - |
| `DELTA_EXCHANGE_API_KEY` | Delta Exchange API key | Yes | - |
| `DELTA_EXCHANGE_API_SECRET` | Delta Exchange API secret | Yes | - |
| `DELTA_EXCHANGE_BASE_URL` | Delta Exchange API base URL | Yes | https://api.india.delta.exchange |
| `QDRANT_URL` | Qdrant vector database URL | No | http://localhost:6333 |
| `QDRANT_API_KEY` | Qdrant API key | No | - |
| `MODEL_DIR` | Directory for model discovery (all models) | No | ./agent/model_storage |
| `MODEL_PATH` | Specific model file path (optional, for direct model loading) | No | agent/model_storage/xgboost/xgboost_BTCUSD_15m.pkl |
| `LOG_LEVEL` | Agent logging level | No | INFO |
| `LOG_DIR` | Agent log directory | No | `./logs/agent` |
| `LOG_RETENTION_DAYS` | Days to retain agent logs | No | 7 |
| `LOG_ARCHIVE_MODE` | `archive` or `delete` previous logs on startup | No | archive |
| `LOG_SESSION_ID` | Optional override for agent session ID | No | - |
| `LOG_FORWARDING_ENABLED` | Toggle remote log forwarding | No | false |
| `LOG_FORWARDING_ENDPOINT` | Remote logging endpoint | No | - |
| `LOG_INCLUDE_STACKTRACE` | Include stack traces in production logs | No | false |

### Frontend Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | Yes | - |
| `NEXT_PUBLIC_WS_URL` | WebSocket URL | Yes | - |

---

## Start the Stack

After you create the environment files above, you can start every service with a single command instead of launching each component manually:

- **macOS/Linux**: `./tools/commands/start.sh`
- **Windows PowerShell**: `powershell -ExecutionPolicy Bypass -File .\tools\commands\start.ps1`
- **Direct Python**: `python tools/commands/start_parallel.py`

The startup system uses a Python-based parallel process manager that starts all services (backend, agent, frontend) simultaneously. Real-time logs are streamed to the console with color-coded service prefixes, and each service also writes to `logs/{service}.log`. The system automatically handles virtual environment setup and dependency installation.

**Parallel Startup Features:**
- All services start at the same time (faster than sequential startup)
- Real-time aggregated log streaming with service identification
- Automatic dependency checking and installation
- Graceful shutdown handling (Ctrl+C stops all services)
- Cross-platform compatibility (Windows, macOS, Linux)

For manual start instructions, see the [Build Guide](11-build-guide.md#project-commands).

---

## Logging Setup

Implement the centralized logging strategy described in [Logging Documentation](12-logging.md) before running any environment:

1. **Directory Layout**
   - Create the base directories `logs/backend`, `logs/agent`, `logs/frontend`, `logs/scripts`, and `logs/archive`.
   - Grant write permissions to the processes that run each service.

2. **Startup Clearing**
   - Each service should clear or archive previous logs during startup and emit a `system.startup` entry with a new `session_id`.
   - The `start` command (`./tools/commands/start.sh` / `start.ps1`, or `python tools/commands/start_parallel.py`) launches services in parallel and manages log files automatically; manual starts should clear logs before launching services.

3. **Structured Logging**
   - Ensure log output is JSON-formatted with `service`, `component`, `session_id`, `correlation_id`, and `environment` fields.
   - Configure `LOG_LEVEL` per environment (`DEBUG` locally, `INFO` or higher in staging/production).

4. **Forwarding (Optional)**
   - When `LOG_FORWARDING_ENABLED=true`, supply `LOG_FORWARDING_ENDPOINT` (e.g., Loki, Elastic, Datadog) and verify connectivity during deployment.

5. **Verification Checklist**
   - After startup, confirm that `logs/*/current.log` was regenerated and `system.startup` entries appear in each log file.
   - Validate logging setup by checking that log directories are writable and logs are being generated correctly.

For detailed retention policies, schema definitions, and troubleshooting tips see [Logging Documentation](12-logging.md).

---

## Monitoring Setup (Optional)

### Prometheus Configuration

**Install Prometheus**:

**Ubuntu/Debian**:
```bash
wget https://github.com/prometheus/prometheus/releases/download/v2.45.0/prometheus-2.45.0.linux-amd64.tar.gz
tar -xzf prometheus-2.45.0.linux-amd64.tar.gz
cd prometheus-2.45.0.linux-amd64
```

**macOS**:
```bash
brew install prometheus
```

**Create `prometheus.yml`**:
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'backend'
    static_configs:
      - targets: ['localhost:8000']

  - job_name: 'agent'
    static_configs:
      - targets: ['localhost:8001']
```

**Start Prometheus**:
```bash
./prometheus --config.file=prometheus.yml
```

**Access Prometheus**:
- URL: http://localhost:9090

---

### Grafana Setup

**Install Grafana**:

**Ubuntu/Debian**:
```bash
sudo apt-get install -y software-properties-common
sudo add-apt-repository "deb https://packages.grafana.com/oss/deb stable main"
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
sudo apt-get update
sudo apt-get install grafana
sudo systemctl start grafana-server
```

**macOS**:
```bash
brew install grafana
brew services start grafana
```

**Access Grafana**:
- URL: http://localhost:3000
- Default credentials: admin/admin

**Add Prometheus Data Source**:
1. Go to Configuration → Data Sources
2. Add Prometheus
3. URL: http://localhost:9090
4. Save and Test
---

## Startup Validation System

The startup system includes comprehensive validation to ensure safe and reliable operation:

### Paper Trading Validation

**Safety Feature**: Prevents accidental live trading by validating environment variables before startup.

- **Environment Variables Checked**: `PAPER_TRADING_MODE`, `TRADING_MODE`
- **Validation Logic**: Blocks startup if live trading mode is detected
- **Error Messages**: Clear warnings with configuration guidance
- **Monitoring Integration**: Status displayed in monitoring dashboard

**Configuration Examples**:
```bash
# Safe paper trading (default)
PAPER_TRADING_MODE=true
TRADING_MODE=paper

# Live trading (blocks startup with warnings)
TRADING_MODE=live
```

### Environment Variable Validation

**Script**: `scripts/validate-env.py`

Validates the root `.env` file for:
- Required database connection strings
- API credentials (Delta Exchange)
- Security keys (JWT, API keys)
- Frontend configuration variables
- Optional service configurations

**Automatic Execution**: Runs during startup sequence Step 3.

### Prerequisite Validation

**Script**: `tools/commands/validate-prerequisites.py`

Validates system requirements:
- Python 3.11+ availability and version
- Node.js 18+ availability and version
- PostgreSQL connection and version
- Redis connection and version

**Automatic Execution**: Runs during startup sequence Step 3.

### Optional Model Validation

**Environment Variable**: `VALIDATE_MODELS_ON_STARTUP=true`

Validates ML model files before startup:
- Model file existence and integrity
- Model loading capability
- Basic prediction functionality

**Default Behavior**: Disabled (set to `false`) for faster startup.

## Health Checks

The system performs comprehensive health checks after service startup:

### Post-Startup Health Verification

**Automatic Execution**: Runs after all services start successfully.

**Services Checked**:
- **Backend**: HTTP GET to `http://localhost:8000/api/v1/health`
- **Feature Server**: HTTP GET to `http://localhost:8001/health`
- **Frontend**: HTTP GET to configured frontend port (default: 3000)

**Success Criteria**:
- HTTP 200 status code
- Response contains expected health data
- Services respond within timeout (default: 5 seconds)

**Error Handling**: Startup continues with warnings if health checks fail.

### Health Check Commands

```bash
# Check all services
python tools/commands/health_check.py

# Enhanced health validation with detailed reporting
python tools/commands/validate-health.py
```

## Monitoring Dashboard

The startup system includes a real-time monitoring dashboard that provides comprehensive system visibility:

### Dashboard Features

**Real-time Updates**: Refreshes every 2 seconds with current system status.

**Service Status Panel**:
- Backend service status (Running/Stopped)
- Agent service status (Running/Stopped)
- Frontend service status (Running/Stopped)

**Paper Trading Status**:
- Clear display of paper/live trading mode
- Safety warnings for live trading configuration

**WebSocket Monitoring**:
- Connection status (Connected/Disconnected)
- Message freshness tracking per message type
- Stale message detection with thresholds

**Data Freshness Tracking**:
- Age tracking for agent_state, market_tick, signal_update messages
- Color-coded freshness indicators (Fresh/Warning/Stale)
- Overall freshness score calculation

**Signal Generation Statistics**:
- Total signals generated
- Average interval between signals
- Signals per hour frequency
- Last signal timestamp and age

### Message Types Monitored

- `agent_state`: Agent state transitions and status
- `market_tick`: Real-time market data updates
- `signal_update`: Trading signal generation
- `reasoning_chain_update`: AI reasoning process updates
- `model_prediction_update`: ML model prediction results
- `portfolio_update`: Portfolio status changes
- `trade_executed`: Trade execution confirmations
- `health_update`: Service health status updates

### Freshness Thresholds

- **Fresh**: < 30 seconds old
- **Warning**: 30-60 seconds old
- **Stale**: > 60 seconds old

### Dashboard Activation

The monitoring dashboard starts automatically when using `start_parallel.py` and runs in the background alongside the services.

---

## Operations & Maintenance Commands
Run these commands from the project root (`JackSparrow/`). Each command is available as a shell script under `tools/commands/` (`.sh` for macOS/Linux, `.ps1` for Windows PowerShell) or can be run directly as Python scripts.

### `start`
Launch all JackSparrow services after the environment is configured using parallel process startup. The startup script automatically validates configuration and prerequisites before starting services.

- macOS/Linux
  ```bash
  ./tools/commands/start.sh
  # or directly:
  python tools/commands/start_parallel.py
  ```
- Windows PowerShell
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\tools\commands\start.ps1
  # or directly:
  python tools\commands\start_parallel.py
  ```

**Actions performed:**
1. Checks and creates virtual environments if needed (backend, agent)
2. Installs Python dependencies if required
3. Installs frontend dependencies if `node_modules` is missing
4. Starts all three services **simultaneously**:
   - FastAPI backend (`http://localhost:8000`)
   - JackSparrow agent
   - Next.js frontend (`http://localhost:3000`)
5. Streams real-time color-coded logs to console with service prefixes
6. Writes individual service logs to `logs/{service}.log`
7. Creates PID files in `logs/` for process management

**Note**: Services handle their own dependency checks (e.g., backend waits for Redis/PostgreSQL). The parallel startup ensures faster initialization while maintaining service reliability.

### `restart`
Perform a clean restart when configuration or dependencies change.

- macOS/Linux
  ```bash
  ./tools/commands/restart.sh
  ```
- Windows PowerShell
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\tools\commands\restart.ps1
  ```

Actions performed:
1. Gracefully stops backend, agent, and frontend processes
2. Clears temporary artefacts (PID files, cached sockets)
3. Re-runs the `start` command
4. Logs to `logs/restart.log`

### `audit`
Run the full project audit pipeline before releases or after major refactors.

- macOS/Linux
  ```bash
  ./tools/commands/audit.sh
  ```
- Windows PowerShell
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\tools\commands\audit.ps1
  ```

Tasks covered:
- Python quality: `ruff check`, `black --check`, `pytest`
- Frontend quality: `npm run lint`, `npm test -- --watch=false`
- Service health: `curl http://localhost:8000/api/v1/health`
- Log review: `grep -E "WARN|ERROR" logs/**/*.log`
- Report output: `logs/audit/report.md`

Refer to the [Audit Report](15-audit-report.md#running-the-audit-command) for interpreting the results.

### `error`
Capture live diagnostics whenever issues are suspected.

- macOS/Linux
  ```bash
  ./tools/commands/error.sh
  ```
- Windows PowerShell
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\tools\commands\error.ps1
  ```

What is collected:
- Process status for backend, agent, and frontend
- Latest 200 log lines per service
- Summary of new warnings/errors since the previous run
- Diagnostic output stored in `logs/error/error-dump-<timestamp>.md`

For deeper inspection guidance, see the [Backend Documentation – Command Operations](06-backend.md#command-operations).

### `validate-prerequisites`
Validate system prerequisites before starting services.

- macOS/Linux
  ```bash
  python tools/commands/validate-prerequisites.py
  ```
- Windows PowerShell
  ```powershell
  python tools\commands\validate-prerequisites.py
  ```

**Validates:**
- Python 3.11+ availability and version
- Node.js 18+ availability and version
- PostgreSQL connection and version
- Redis connection and version

### `health_check`
Perform health checks on running services.

- macOS/Linux
  ```bash
  python tools/commands/health_check.py
  ```
- Windows PowerShell
  ```powershell
  python tools\commands\health_check.py
  ```

**Checks:**
- Backend service health (`http://localhost:8000/api/v1/health`)
- Feature server health (`http://localhost:8001/health`)
- Frontend accessibility

### `validate-health`
Enhanced health validation with detailed reporting.

- macOS/Linux
  ```bash
  python tools/commands/validate-health.py
  ```
- Windows PowerShell
  ```powershell
  python tools\commands\validate-health.py
  ```

**Provides:**
- Detailed health status for all services
- Performance metrics and latency information
- Recommendations for failed services

---

## Troubleshooting

Review [Logging Documentation](12-logging.md) for detailed log inspection workflows, startup clearing procedures, and retention policies. Use the guidance below for environment-specific issues.

### Common Issues

#### Database Connection Errors

**Problem**: Cannot connect to PostgreSQL

**Solutions**:
1. Verify PostgreSQL is running:
   ```bash
   sudo systemctl status postgresql
   ```

2. Check connection string format:
   ```
   postgresql://user:password@host:port/database
   ```

3. Verify database exists:
   ```bash
   psql -l | grep trading_agent
   ```

4. Check firewall settings

---

#### Redis Connection Errors

**Problem**: Cannot connect to Redis

**Solutions**:
1. Verify Redis is running:
   ```bash
   redis-cli ping
   ```

2. Check Redis URL format:
   ```
   redis://host:port/db
   ```

3. Verify Redis is accessible:
   ```bash
   redis-cli -h localhost -p 6379 ping
   ```

---

#### Agent Not Responding

**Problem**: Agent not responding to backend requests

**Solutions**:
1. Check agent logs for errors (`logs/agent/current.log` or `logs/agent.log`)
2. Verify message queue is working
3. Check agent state machine status (see [Logic & Reasoning Documentation](05-logic-reasoning.md#enhanced-agent-state-machine))
4. Verify agent has database access
5. Check for deadlock conditions

---

#### WebSocket Connection Issues

**Problem**: Frontend cannot connect to WebSocket

**Solutions**:
1. Verify backend is running on correct port
2. Check WebSocket URL in frontend config
3. Check CORS settings in backend
4. Verify firewall allows WebSocket connections
5. Check browser console for errors

---

#### Frontend Startup Errors

**Problem**: `npm run dev` exits immediately with missing environment variables.

**Solutions**:
1. Confirm the root `.env` file contains `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL`. Copy from `.env.example` if necessary.
2. Ensure Node.js 18+ is installed: `node --version` should report `v18.x` or newer. Upgrade via `nvm`, `fnm`, or the installer if required.
3. Remove `.next/` and reinstall dependencies to clear stale build artefacts: `rm -rf .next node_modules && npm install`.
4. Check for port conflicts on `3000` using `npx kill-port 3000` (macOS/Linux) or `Get-NetTCPConnection -LocalPort 3000` (Windows) and stop the offending process.
5. Review `frontend/.next/logs/latest.log` (generated by the `start` command) for stack traces that point to misconfigured imports or missing TypeScript types.

---

#### Model Loading Errors

**Problem**: Models fail to load

**Solutions**:
1. Verify model files exist (check MODEL_DIR for model discovery or MODEL_PATH for specific model file)
2. Check model file permissions
3. Verify model format compatibility
4. Check available memory
5. Review model loading logs

---

#### Feature Server Errors

**Problem**: Feature computation fails

**Solutions**:
1. Verify market data is available
2. Check feature computation logs
3. Verify feature definitions
4. Check data quality
5. Review feature server health

---

#### Paper Trading Validation Failed

**Problem**: Startup blocked with "PAPER TRADING (Safe)" or live trading warnings

**Solutions**:
1. Check `PAPER_TRADING_MODE` and `TRADING_MODE` environment variables
2. Set `PAPER_TRADING_MODE=true` or `TRADING_MODE=paper` for safe operation
3. Remove or comment out live trading configuration
4. Verify `.env` file has correct paper trading settings

---

#### Environment Validation Failed

**Problem**: `validate-env.py` reports configuration errors

**Solutions**:
1. Run manual validation: `python scripts/validate-env.py`
2. Check required environment variables are set:
   - `DATABASE_URL` - PostgreSQL connection string
   - `DELTA_EXCHANGE_API_KEY` - API credentials
   - `DELTA_EXCHANGE_API_SECRET` - API credentials
   - `JWT_SECRET_KEY` - Security key
   - `API_KEY` - API access key
3. Verify variable formats and values
4. Check `.env` file permissions and location

---

#### Prerequisite Validation Failed

**Problem**: `validate-prerequisites.py` reports system requirement issues

**Solutions**:
1. Run manual validation: `python tools/commands/validate-prerequisites.py`
2. Verify Python 3.11+: `python --version`
3. Verify Node.js 18+: `node --version`
4. Check PostgreSQL connection: `psql -d trading_agent -c "SELECT 1"`
5. Check Redis connection: `redis-cli ping`
6. Install missing dependencies
7. Update PATH if commands not found

---

#### Model Validation Failed

**Problem**: Model validation fails during startup (when `VALIDATE_MODELS_ON_STARTUP=true`)

**Solutions**:
1. Check model files exist in `agent/model_storage/`
2. Verify model file integrity and format
3. Check available disk space and memory
4. Review model loading error messages
5. Disable validation with `VALIDATE_MODELS_ON_STARTUP=false` for faster startup
6. Re-train models if corrupted: `python scripts/train_models.py`

---

#### Health Check Failures

**Problem**: Services fail health checks after startup

**Solutions**:
1. Run manual health check: `python tools/commands/health_check.py`
2. Check service logs in `logs/` directory
3. Verify ports are available (8000, 8001, 3000)
4. Check database and Redis connectivity
5. Restart services if health checks fail
6. Review detailed health validation: `python tools/commands/validate-health.py`

---

### Debugging Tips

**Enable Debug Logging**:
```bash
export LOG_LEVEL=DEBUG
```

**Verify Logging Setup**:
```bash
# Check that log directories exist and are writable
ls -la logs/backend logs/agent logs/frontend

# Verify logs are being generated
tail -f logs/backend/current.log
tail -f logs/agent/current.log
```

**Manually Clear Logs Before Restart**:
```bash
python scripts/logging/bootstrap.py --service backend
python scripts/logging/bootstrap.py --service agent
npm run log:bootstrap         # frontend helper
```

**Check Service Health**:
```bash
curl http://localhost:8000/api/v1/health
```

**View Database Queries**:
Enable SQL logging in SQLAlchemy:
```python
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

**Monitor Redis**:
```bash
redis-cli monitor
```

**Check Service Logs**:
- Backend logs: `logs/backend/current.log` (rotated per session)
- Agent logs: `logs/agent/current.log`
- Frontend logs: `logs/frontend/current.log` (server-side) and browser console (client-side)

---

## Production Deployment Considerations

### Security Checklist

- [ ] Use strong, unique passwords
- [ ] Enable HTTPS/TLS
- [ ] Set up firewall rules
- [ ] Use environment variables for secrets
- [ ] Enable authentication
- [ ] Set up rate limiting
- [ ] Enable CORS properly
- [ ] Regular security updates

### Performance Optimization

- [ ] Enable database connection pooling
- [ ] Configure Redis caching
- [ ] Set up CDN for frontend
- [ ] Enable gzip compression
- [ ] Optimize database queries
- [ ] Use load balancing for backend
- [ ] Set up monitoring and alerts

### Backup Strategy

- [ ] Regular database backups
- [ ] Model file backups
- [ ] Configuration backups
- [ ] Test restore procedures

---

## Docker Deployment (Alternative)

Docker provides an alternative deployment method that containerizes all services and dependencies, simplifying setup and ensuring consistent environments across development, testing, and production.

### Prerequisites

**Required Software**:
- Docker Engine 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- Docker Compose 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))

**Verify Installation**:
```bash
docker --version
docker-compose --version
```

---

### Docker Architecture

The Docker deployment uses a multi-container architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Backend  │  │  Agent   │  │ Frontend │             │
│  │ :8000    │  │          │  │  :3000   │             │
│  └────┬──────┘  └────┬──────┘  └────┬──────┘             │
│       │             │             │                     │
│       └─────────────┴─────────────┘                     │
│                  │                                      │
│       ┌──────────┼──────────┐                          │
│       │          │          │                          │
│  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐                     │
│  │Postgres│ │ Redis  │ │ Qdrant │                     │
│  │ :5432  │ │ :6379  │ │ :6333  │                     │
│  └────────┘ └────────┘ └────────┘                      │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

All containers communicate via Docker's internal network using service names as hostnames.

---

### Dockerfile Examples

#### Backend Dockerfile

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run backend
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Agent Dockerfile

Create `agent/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for ML libraries
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create model storage directory (mounted as volume in docker-compose)
# Models are mounted at runtime, but this ensures directory exists
RUN mkdir -p /app/agent/model_storage/xgboost

# Run agent
CMD ["python", "-m", "agent.core.intelligent_agent"]
```

#### Frontend Dockerfile

Create `frontend/Dockerfile`:

```dockerfile
FROM node:18-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build Next.js application
RUN npm run build

# Production stage
FROM node:18-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Copy package files
COPY package*.json ./

# Install production dependencies only
RUN npm ci --only=production

# Copy built application from builder
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public

# Expose port
EXPOSE 3000

# Run Next.js
CMD ["npm", "start"]
```

---

### Docker Compose Configuration

Create `docker-compose.yml` in the project root:

```yaml
version: '3.8'

services:
  # PostgreSQL with TimescaleDB
  postgres:
    image: timescale/timescaledb:latest-pg15
    container_name: jacksparrow-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: trading_agent
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - jacksparrow-network

  # Redis
  redis:
    image: redis:7-alpine
    container_name: jacksparrow-redis
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - jacksparrow-network

  # Qdrant Vector Database (Optional)
  qdrant:
    image: qdrant/qdrant:latest
    container_name: jacksparrow-qdrant
    ports:
      - "${QDRANT_PORT:-6333}:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:6333/health"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - jacksparrow-network

  # Backend Service
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: jacksparrow-backend
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-changeme}@postgres:5432/trading_agent
      - REDIS_URL=redis://redis:6379
      - QDRANT_URL=http://qdrant:6333
      - DELTA_EXCHANGE_API_KEY=${DELTA_EXCHANGE_API_KEY}
      - DELTA_EXCHANGE_API_SECRET=${DELTA_EXCHANGE_API_SECRET}
      - DELTA_EXCHANGE_BASE_URL=${DELTA_EXCHANGE_BASE_URL:-https://api.india.delta.exchange}
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - API_KEY=${API_KEY}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs/backend
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    volumes:
      - ./logs:/app/logs
      - ./backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    networks:
      - jacksparrow-network
    restart: unless-stopped

  # Agent Service
  agent:
    build:
      context: ./agent
      dockerfile: Dockerfile
    container_name: jacksparrow-agent
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-changeme}@postgres:5432/trading_agent
      - REDIS_URL=redis://redis:6379
      - QDRANT_URL=http://qdrant:6333
      - DELTA_EXCHANGE_API_KEY=${DELTA_EXCHANGE_API_KEY}
      - DELTA_EXCHANGE_API_SECRET=${DELTA_EXCHANGE_API_SECRET}
      - DELTA_EXCHANGE_BASE_URL=${DELTA_EXCHANGE_BASE_URL:-https://api.india.delta.exchange}
      - MODEL_DIR=/app/agent/model_storage
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - LOG_DIR=/app/logs/agent
    volumes:
      - ./agent/model_storage:/app/agent/model_storage
      - ./logs:/app/logs
      - ./agent:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      backend:
        condition: service_started
    networks:
      - jacksparrow-network
    restart: unless-stopped

  # Frontend Service
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: jacksparrow-frontend
    environment:
      - NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL:-http://localhost:8000}
      - NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL:-ws://localhost:8000/ws}
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    depends_on:
      - backend
    networks:
      - jacksparrow-network
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  qdrant_data:

networks:
  jacksparrow-network:
    driver: bridge
```

---

### Environment Variables

Create a `.env` file in the project root for Docker Compose:

```bash
# Database Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_PORT=5432

# Redis Configuration
REDIS_PORT=6379

# Qdrant Configuration
QDRANT_PORT=6333

# Service Ports
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Delta Exchange API
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret
DELTA_EXCHANGE_BASE_URL=https://api.india.delta.exchange

# Security
JWT_SECRET_KEY=your_jwt_secret_key_here
API_KEY=your_api_key_here

# Logging
LOG_LEVEL=INFO

# Frontend Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

**Note**: For production deployments, use Docker secrets or external secret management systems instead of plain `.env` files.

---

### Building and Running

#### Build All Services

```bash
# Build all Docker images
docker-compose build

# Build specific service
docker-compose build backend
```

#### Start Services

```bash
# Start all services in detached mode
docker-compose up -d

# Start with logs visible
docker-compose up

# Start specific services
docker-compose up -d postgres redis qdrant
docker-compose up -d backend agent frontend
```

#### Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v
```

#### View Logs

```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f agent
docker-compose logs -f frontend

# View last 100 lines
docker-compose logs --tail=100 backend
```

#### Execute Commands in Containers

```bash
# Run database migrations
docker-compose exec backend python scripts/setup_db.py

# Access PostgreSQL
docker-compose exec postgres psql -U postgres -d trading_agent

# Access Redis CLI
docker-compose exec redis redis-cli

# Run tests
docker-compose exec backend pytest
docker-compose exec agent pytest
```

---

### Development Workflow with Hot-Reload

The project includes a development Docker setup that enables hot-reload, allowing code changes to be reflected immediately without rebuilding Docker images.

> **📖 For comprehensive hot reload documentation**, see [Docker Hot Reload Guide](docker-hot-reload.md)

#### Quick Start

**Start development environment:**
```bash
# Using helper scripts (recommended)
./scripts/docker/dev-start.sh --build
# or on Windows
.\scripts\docker\dev-start.ps1 -Build

# Or manually
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

**Start with specific service:**
```bash
scripts/docker/dev-start.ps1 backend
scripts/docker/dev-start.sh backend
```

#### How It Works

The development setup uses `docker-compose.dev.yml` which:

1. **Mounts source code as volumes**: Code changes are immediately visible inside containers
   - `./backend:/app/backend:rw` - Backend source code
   - `./agent:/app/agent:rw` - Agent source code
   - `./frontend:/app:rw` - Frontend source code (excluding `node_modules` and `.next`)

2. **Uses development Dockerfiles**: `Dockerfile.dev` files install dependencies only (no source code COPY)

3. **Enables hot-reload**:
   - **Backend**: `uvicorn --reload` automatically restarts on Python file changes
   - **Frontend**: Next.js dev server (`npm run dev`) provides hot module replacement (HMR)
   - **Agent**: Custom file watcher (`watchdog`) monitors Python files and restarts the agent process on changes

#### Development vs Production

**Development Mode** (`docker-compose.dev.yml`):
- ✅ Hot-reload enabled
- ✅ Source code mounted as volumes
- ✅ Faster iteration (no rebuild needed)
- ✅ Development dependencies included
- ⚠️ Not optimized for production performance

**Production Mode** (`docker-compose.yml`):
- ✅ Optimized builds
- ✅ Source code baked into images
- ✅ Production dependencies only
- ✅ Better security and performance
- ⚠️ Requires rebuild for code changes

#### Development Commands

**Start development environment:**
```bash
# First time (builds images)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Subsequent starts (uses cached images)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

**View logs:**
```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f agent

# Filter logs by level (example: ERROR)
docker-compose logs backend | grep ERROR
```

**Start specific container:**
```bash
docker-compose up -d backend
```

**Audit errors:**
```bash
# Check for errors in logs
docker-compose logs | grep -i error

# Check service status
docker-compose ps
```

#### Troubleshooting

**Code changes not reflecting:**
- Ensure you're using `docker-compose.dev.yml` override: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps`
- Check volume mounts: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml config | grep volumes`
- Verify file permissions on mounted volumes
- Check logs for reload/restart messages: `docker-compose logs -f backend | grep -i reload`

**Agent not restarting:**
- Verify watchdog is installed: `docker-compose exec agent pip list | grep watchdog`
- Check agent watcher logs: `docker-compose logs -f agent | grep -i watcher`
- Manually restart: `docker-compose restart agent`

**Frontend not updating:**
- Check Next.js dev server is running: `docker-compose logs frontend | grep -i ready`
- Hard refresh browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (macOS)
- Check for compilation errors: `docker-compose logs -f frontend`

**Performance issues:**
- Development mode is slower than production (by design)
- Use production mode for performance testing
- Consider excluding large directories from volumes

**Port conflicts:**
- Check if ports are already in use: `netstat -an | grep 8000` (Unix) or `netstat -ano | findstr :8000` (Windows)
- Modify ports in `.env` file if needed

> **💡 For detailed troubleshooting**, see [Docker Hot Reload Guide - Troubleshooting](docker-hot-reload.md#troubleshooting)

#### Best Practices

1. **Use development mode** for active coding and debugging
2. **Use production mode** for final testing and deployment
3. **Rebuild images** when dependencies change (`--Build` flag)
4. **Monitor logs** regularly for errors (`docker-compose logs -f`)
5. **Run audits** before committing (check logs with `docker-compose logs | grep -i error`)

#### Production Configuration

For production, consider:

1. **Multi-stage builds**: Already implemented in frontend Dockerfile
2. **Resource limits**: Add to docker-compose.yml:
   ```yaml
   backend:
     deploy:
       resources:
         limits:
           cpus: '2'
           memory: 2G
         reservations:
           cpus: '1'
           memory: 1G
   ```

3. **Health checks**: Already included in docker-compose.yml
4. **Restart policies**: Set to `unless-stopped` for automatic recovery
5. **Security**: Run containers as non-root users
6. **Secrets management**: Use Docker secrets or external systems

---

### Initial Setup with Docker

1. **Create Environment File**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Initialize Database**:
   ```bash
   # Start database services
   docker-compose up -d postgres redis qdrant
   
   # Wait for services to be healthy
   docker-compose ps
   
   # Run database migrations
   docker-compose exec backend python scripts/setup_db.py
   ```

3. **Start All Services**:
   ```bash
   docker-compose up -d
   ```

4. **Verify Installation**:
   ```bash
   # Check all services are running
   docker-compose ps
   
   # Check backend health
   curl http://localhost:8000/api/v1/health
   
   # Access frontend
   open http://localhost:3000
   ```

---

### Troubleshooting Docker Deployment

#### Port Conflicts

**Problem**: Port already in use

**Solution**:
```bash
# Check what's using the port
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Change port in .env file
BACKEND_PORT=8001
```

#### Volume Permission Issues

**Problem**: Permission denied when writing to mounted volumes

**Solution**:
```bash
# Fix permissions for logs directory
sudo chown -R $USER:$USER logs/

# Or run container with user mapping
# Add to docker-compose.yml:
user: "${UID}:${GID}"
```

#### Database Connection Errors

**Problem**: Cannot connect to PostgreSQL

**Solution**:
```bash
# Verify database is healthy
docker-compose ps postgres

# Check database logs
docker-compose logs postgres

# Verify connection string uses service name 'postgres', not 'localhost'
DATABASE_URL=postgresql://postgres:password@postgres:5432/trading_agent
```

#### Model Files Not Found

**Problem**: Agent cannot find model files

**Solution**:
```bash
# Verify model storage directory is mounted
docker-compose exec agent ls -la /app/agent/model_storage

# Check volume mount in docker-compose.yml
volumes:
  - ./agent/model_storage:/app/agent/model_storage
```

#### Container Build Failures

**Problem**: Docker build fails

**Solution**:
```bash
# Build with verbose output
docker-compose build --no-cache --progress=plain backend

# Check Dockerfile syntax
docker build -t test-backend ./backend
```

#### Service Dependencies Not Ready

**Problem**: Services start before dependencies are ready

**Solution**:
- Health checks are already configured in docker-compose.yml
- Use `depends_on` with `condition: service_healthy`
- Services will wait for dependencies to be healthy before starting

#### Network Connectivity Issues

**Problem**: Services cannot communicate

**Solution**:
```bash
# Verify all services are on same network
docker network inspect jacksparrow_jacksparrow-network

# Test connectivity from container
docker-compose exec backend ping postgres
docker-compose exec backend ping redis
```

#### Logs Not Persisting

**Problem**: Logs disappear after container restart

**Solution**:
- Logs are mounted to `./logs` directory
- Verify volume mount in docker-compose.yml
- Check directory permissions

---

### Docker Compose Commands Reference

| Command | Description |
|---------|-------------|
| `docker-compose up -d` | Start all services in background |
| `docker-compose down` | Stop and remove containers |
| `docker-compose ps` | List running containers |
| `docker-compose logs -f [service]` | Follow logs for service |
| `docker-compose exec [service] [cmd]` | Execute command in container |
| `docker-compose build [service]` | Build service image |
| `docker-compose restart [service]` | Restart service |
| `docker-compose stop [service]` | Stop service |
| `docker-compose start [service]` | Start stopped service |
| `docker-compose pull` | Pull latest images |
| `docker-compose config` | Validate configuration |

---

### Production Deployment Checklist

When deploying to production with Docker:

- [ ] Use strong passwords in `.env` file
- [ ] Enable HTTPS/TLS (use reverse proxy like nginx)
- [ ] Set resource limits for containers
- [ ] Configure log rotation
- [ ] Set up automated backups for volumes
- [ ] Use Docker secrets for sensitive data
- [ ] Enable container health monitoring
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerting
- [ ] Test disaster recovery procedures
- [ ] Document container restart procedures
- [ ] Set up CI/CD for automated deployments

---

## Related Documentation

- [Architecture Documentation](01-architecture.md) - System design
- [Backend Documentation](06-backend.md) - API implementation
- [Logging Documentation](12-logging.md) - Centralized logging plan and procedures
- [Frontend Documentation](07-frontend.md) - Frontend implementation
- [Docker Hot Reload Guide](docker-hot-reload.md) - Hot reload setup and usage
- [Project Rules](14-project-rules.md) - Development standards

---

