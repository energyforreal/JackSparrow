# Build Guide

## Overview

This guide provides step-by-step instructions to build and run the entire JackSparrow project from scratch. Follow these instructions sequentially to set up a complete development and testing environment.

**Goal**: By following this guide, you will have a fully functional JackSparrow trading agent running locally with all components operational.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites Check](#prerequisites-check)
- [Step 1: Clone Repository](#step-1-clone-repository)
- [Step 2: Database Setup](#step-2-database-setup)
- [Step 3: Redis Setup](#step-3-redis-setup)
- [Step 4: Vector Database Setup (Optional)](#step-4-vector-database-setup-optional)
- [Step 5: Backend Setup](#step-5-backend-setup)
- [Step 6: Agent Setup](#step-6-agent-setup)
- [Step 7: Frontend Setup](#step-7-frontend-setup)
- [Step 8: Start Services](#step-8-start-services)
- [Project Commands](#project-commands)
- [Step 9: Verify Installation](#step-9-verify-installation)
- [Step 10: Upload ML Models (Optional)](#step-10-upload-ml-models-optional)
- [Step 11: Run Tests (Optional)](#step-11-run-tests-optional)
- [Troubleshooting](#troubleshooting)
- [Quick Start Script](#quick-start-script)
- [Next Steps](#next-steps)
- [Related Documentation](#related-documentation)
- [Build Verification Checklist](#build-verification-checklist)

---

## Prerequisites Check

Before starting, verify you have the required software installed:

```bash
# Check Python version (requires 3.11+)
python --version

# Check Node.js version (requires 18+)
node --version

# Check npm version
npm --version

# Check PostgreSQL (requires 15+)
psql --version

# Check Redis (requires 7.0+)
redis-cli --version

# Check Git
git --version
```

If any are missing, install them before proceeding. See [Deployment Documentation](10-deployment.md#development-environment-setup) for installation instructions.

> **Alternative Deployment Method**: Docker provides an alternative deployment option that containerizes all services and dependencies. If you prefer using Docker, see the [Docker Deployment section](10-deployment.md#docker-deployment-alternative) in the Deployment Documentation for complete instructions on deploying with Docker and Docker Compose.

---

## Step 1: Clone Repository

```bash
# Clone the repository
git clone https://github.com/energyforreal/JackSparrow
cd JackSparrow

# Verify repository structure
ls -la
```

Expected structure:
```
JackSparrow/
├── backend/
├── agent/
├── frontend/
├── docs/
├── scripts/
└── tests/
```

---

## Step 2: Database Setup

### 2.1 Install PostgreSQL with TimescaleDB

**Ubuntu/Debian**:
```bash
sudo apt update
sudo apt install postgresql-15 postgresql-contrib
sudo apt install timescaledb-2-postgresql-15
sudo timescaledb-tune
sudo systemctl restart postgresql
```

**macOS**:
```bash
brew install postgresql@15
brew install timescaledb
brew services start postgresql@15
```

**Windows**:
- Download PostgreSQL 15 from https://www.postgresql.org/download/windows/
- Install TimescaleDB extension separately

### 2.2 Create Database

```bash
# Create database user (if needed)
sudo -u postgres createuser -P trading_agent_user
# Enter password when prompted

# Create database
createdb -U trading_agent_user trading_agent

# Connect and enable TimescaleDB
psql -U trading_agent_user -d trading_agent -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

# Verify installation
psql -U trading_agent_user -d trading_agent -c "\dx"
```

Expected output should show `timescaledb` extension.

---

## Step 3: Redis Setup

### 3.1 Install Redis

**Ubuntu/Debian**:
```bash
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis
```

**macOS**:
```bash
brew install redis
brew services start redis
```

**Windows**:
- Download Redis from https://github.com/microsoftarchive/redis/releases
- Run `redis-server.exe`

### 3.2 Verify Redis

```bash
redis-cli ping
# Should return: PONG
```

---

## Step 4: Vector Database Setup (Optional)

### 4.1 Install Qdrant

**Ubuntu/Debian**:
```bash
wget https://github.com/qdrant/qdrant/releases/download/v1.7.0/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
cd qdrant-x86_64-unknown-linux-gnu
./qdrant &
```

**macOS**:
```bash
brew install qdrant
qdrant &
```

**Windows**:
- Download Qdrant binary from https://github.com/qdrant/qdrant/releases
- Extract and run `qdrant.exe`

### 4.2 Verify Qdrant

```bash
curl http://localhost:6333/health
# Should return: {"status":"ok"}
```

---

## Step 5: Backend Setup

### 5.1 Create Virtual Environment

```bash
cd backend
python -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 5.2 Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.3 Configure Environment Variables

**Single Root `.env` File**: All services (backend, agent, frontend) read from a **single root `.env` file** in the project root directory. The backend reads from this file via `ROOT_ENV_PATH` in `backend/core/config.py`.

**Setup Instructions:**

```bash
# From project root directory
# Copy the example template
cp .env.example .env

# Edit .env with your actual values
# Required variables:
#   - DATABASE_URL
#   - DELTA_EXCHANGE_API_KEY
#   - DELTA_EXCHANGE_API_SECRET
#   - JWT_SECRET_KEY
#   - API_KEY
```

**Minimum Required Variables:**

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://trading_agent_user:your_password@localhost:5432/trading_agent

# Redis (default: redis://localhost:6379)
REDIS_URL=redis://localhost:6379

# Delta Exchange (REQUIRED - Paper Trading)
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret
DELTA_EXCHANGE_BASE_URL=https://api.india.delta.exchange

# Security (REQUIRED)
JWT_SECRET_KEY=your_secret_key_here_minimum_32_characters
API_KEY=your_api_key_here_minimum_32_characters
```

**Note**: See `.env.example` in the project root for the complete list of all available environment variables. The backend automatically reads from the root `.env` file - no service-specific `.env` files are needed.

### 5.4 Initialize Database

**Important**: Database initialization must be completed before starting services.

```bash
# From project root directory
python scripts/setup_db.py
```

This script will:
- Enable TimescaleDB extension
- Create all required tables (trades, positions, decisions, performance_metrics, model_performance)
- Convert time-series tables to hypertables for optimal performance
- Create necessary indexes

**Troubleshooting**:
- Ensure PostgreSQL is running: `pg_isready` or `psql -U postgres -c "SELECT 1"`
- Verify TimescaleDB is installed: `psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"`
- Check DATABASE_URL in the root `.env` file is correct

### 5.5 Verify Backend Setup

```bash
cd ../backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -c "from api.main import app; print('Backend imports successful')"
```

---

## Step 6: Agent Setup

### 6.1 Create Virtual Environment

```bash
cd ../agent
python -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 6.2 Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Note**: This may take several minutes as it includes ML libraries (XGBoost, TensorFlow, etc.).

### 6.3 Create Model Storage Directory

**Note**: All trained ML models are stored in the `agent/model_storage/` directory. Models are automatically discovered and registered on agent startup.

```bash
# Create model storage directories (if they don't exist)
mkdir -p agent/model_storage/custom
mkdir -p agent/model_storage/xgboost
mkdir -p agent/model_storage/lstm
mkdir -p agent/model_storage/transformer
```

### 6.4 Configure Environment Variables

**Single Root `.env` File**: The agent reads from the **same root `.env` file** used by the backend. The agent reads from this file via `ROOT_ENV_PATH` in `agent/core/config.py`.

**Setup Instructions:**

If you haven't already created the root `.env` file (from Step 5.3), do so now:

```bash
# From project root directory
# Copy the example template (if not already done)
cp .env.example .env

# Edit .env with your actual values
# The agent shares the same .env file as the backend
```

**Agent-Specific Variables (Optional):**

These variables can be added to the root `.env` file if you need to customize agent behavior:

```bash
# Model Configuration
# Use model discovery for models in agent/model_storage/
MODEL_DIR=./agent/model_storage
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true

# Agent Configuration (defaults provided)
AGENT_START_MODE=MONITORING
AGENT_SYMBOL=BTCUSD
AGENT_INTERVAL=15m

# Risk Management (defaults provided)
MAX_POSITION_SIZE=0.10
MAX_PORTFOLIO_HEAT=0.30
STOP_LOSS_PERCENTAGE=0.02
TAKE_PROFIT_PERCENTAGE=0.05
MAX_DAILY_LOSS=0.05
MAX_DRAWDOWN=0.15
MAX_CONSECUTIVE_LOSSES=5
MIN_TIME_BETWEEN_TRADES=300
```

**Note**: See `.env.example` in the project root for the complete list of all available environment variables. The template is already segmented by service domain (infrastructure, Delta Exchange credentials, backend security, agent configuration, frontend, optional services), so copy it as-is and only change the values. The agent automatically reads from the root `.env` file - no service-specific `.env` files are needed.

### 6.5 Verify Agent Setup

```bash
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -c "from agent.core.intelligent_agent import IntelligentAgent; print('Agent imports successful')"
```

---

## Step 7: Frontend Setup

### 7.1 Install Dependencies

```bash
cd ../frontend
npm install
```

**Note**: This may take a few minutes to download all Node.js packages.

### 7.2 Configure Environment Variables

**Single Root `.env` File**: The frontend reads from the **same root `.env` file** used by backend and agent. The frontend reads from this file via `loadRootEnv()` function in `frontend/next.config.js`.

**Setup Instructions:**

If you haven't already created the root `.env` file (from Step 5.3), do so now:

```bash
# From project root directory
# Copy the example template (if not already done)
cp .env.example .env

# Edit .env and ensure these frontend variables are set:
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

**Note**: The frontend automatically reads `NEXT_PUBLIC_*` variables from the root `.env` file. No `frontend/.env.local` file is needed. See `.env.example` for the complete list of frontend variables.

### 7.3 Verify Frontend Setup

```bash
npm run build
# Should complete without errors
```

---

## Step 7.5: Validate Configuration and Prerequisites

**Important**: Before starting services, validate your configuration and prerequisites to catch issues early.

### Validate Environment Variables

```bash
python scripts/validate-env.py
```

This checks:
- All required variables are present
- Variable formats are correct (URLs, connection strings)
- Security keys meet minimum requirements
- Model files exist in MODEL_DIR

### Validate Prerequisites

```bash
python tools/commands/validate-prerequisites.py
```

This checks:
- Python 3.11+ is installed
- Node.js 18+ is installed
- PostgreSQL is running and accessible
- Redis is running and accessible
- Database schema is initialized (tables exist)
- Service ports are available

### Quick Validation Command

Run both validations at once:

```bash
python scripts/validate-env.py && python tools/commands/validate-prerequisites.py
```

**If validation fails:**
1. Review the error messages
2. Fix issues in your `.env` file or start missing services
3. Re-run validation until all checks pass
4. See [Troubleshooting Guide](troubleshooting-local-startup.md) for detailed help

**Note**: The startup script (`python tools/commands/start_parallel.py`) automatically runs these validations before starting services, but it's recommended to run them manually first to catch issues early.

---

## Step 8: Start Services

**Recommended**: Use the parallel startup script for faster initialization and automatic validation.

### 8.1 Pre-Startup Validation (Recommended)

Before starting services, validate your configuration:

```bash
# Validate environment variables
python scripts/validate-env.py

# Validate system prerequisites
python tools/commands/validate-prerequisites.py

# Optional: Validate model files (set VALIDATE_MODELS_ON_STARTUP=true in .env)
```

### 8.2 Parallel Startup (Recommended)

Start all services simultaneously with automatic validation:

```bash
# From project root directory
python tools/commands/start_parallel.py
```

**Startup Sequence Performed:**
1. **Environment Loading**: Loads and validates `.env` configuration
2. **Paper Trading Validation**: Verifies safe paper trading mode (blocks live trading)
3. **Redis Availability**: Checks Redis service and attempts auto-startup if needed
4. **Configuration Validation**: Runs environment variable and prerequisite validation
5. **Optional Model Validation**: Validates ML model files if enabled
6. **Service Dependencies**: Ensures all dependencies are properly set up
7. **Parallel Startup**: Launches backend, agent, and frontend services simultaneously
8. **Health Checks**: Performs post-startup health verification
9. **Monitoring Dashboard**: Activates real-time monitoring with data freshness tracking

**Expected Output:**
```
JackSparrow Trading Agent - Startup Sequence
Process ID: 12345
Project root: /path/to/JackSparrow

Step 1/4: Loading environment configuration...
Step 2/4: Checking Redis availability...
[PAPER TRADING] Validating configuration...
[PAPER TRADING] ✓ Mode: PAPER TRADING (Safe)
Step 3/4: Running configuration validators...
Step 4/4: Ensuring service dependencies...

[BACKEND] INFO: Uvicorn running on http://127.0.0.1:8000
[AGENT] INFO: Agent initialized
[FRONTEND] - ready started server on 0.0.0.0:3000

Running health checks...
✓ Backend: healthy
✓ Feature Server: healthy
✓ Frontend: healthy

Monitoring dashboard started - refresh rate: 2s
```

### 8.3 Alternative: Manual Startup

If you prefer separate terminals (not recommended for production):

#### Terminal 1: Backend
```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn api.main:app --reload --port 8000
```

#### Terminal 2: Agent
```bash
cd agent
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -m agent.core.intelligent_agent
```

#### Terminal 3: Frontend
```bash
cd frontend
npm run dev
```

### 8.4 Verification Checklist

After successful parallel startup:

#### Automatic Verification (Built-in)
The startup script automatically performs:
- ✅ **Health Checks**: HTTP endpoints verified for backend, feature server, and frontend
- ✅ **Configuration Validation**: Environment variables and prerequisites validated
- ✅ **Paper Trading Safety**: Live trading mode blocked with clear warnings
- ✅ **Monitoring Dashboard**: Real-time monitoring activated

#### Manual Verification Steps
1. **Check Startup Output**: Verify all services show "healthy" in the startup summary
2. **Visit Dashboard**: `http://localhost:3000` should load without console errors
3. **API Health Check**: Visit `http://localhost:8000/api/v1/health` - should show health score ≥ 0.90
4. **Monitoring Dashboard**: Look for real-time updates showing service status and paper trading mode
5. **Test Prediction**: Run `curl -X POST http://localhost:8000/api/v1/predict -d '{}' -H 'Content-Type: application/json'` and verify response
6. **Check Logs**: Review `logs/start.log` for any WARN/ERROR entries

#### Troubleshooting Startup Issues
If startup fails:
- **Paper Trading Error**: Check `PAPER_TRADING_MODE` and `TRADING_MODE` in `.env`
- **Validation Failed**: Run `python scripts/validate-env.py` and `python tools/commands/validate-prerequisites.py`
- **Health Check Failed**: Run `python tools/commands/health_check.py` to diagnose service issues
- **Port Conflicts**: Ensure ports 8000, 8001, and 3000 are available

---

## Project Commands

The project provides Python scripts and shell scripts for managing the JackSparrow stack. Run these commands from the repository root (`JackSparrow/`).

### Validation Commands

**Validate environment variables and prerequisites:**
```bash
# Run both validations
python scripts/validate-env.py && python tools/commands/validate-prerequisites.py

# Or run individually:
python scripts/validate-env.py
python tools/commands/validate-prerequisites.py
```

**Recommended**: Run validation before starting services to catch configuration issues early.

### Start Services

**Start all services (parallel startup):**
```bash
# Direct Python execution (recommended)
python tools/commands/start_parallel.py

# Or use shell scripts:
# Linux/macOS:
./tools/commands/start.sh

# Windows PowerShell:
.\tools\commands\start.ps1
```

**Features:**
- Launches backend (`uvicorn`), agent (`python -m agent.core.intelligent_agent`), and frontend (`npm run dev`) **simultaneously** using parallel process manager
- **Automatically validates** environment and prerequisites before starting services
- Automatically sets up virtual environments and installs dependencies if needed
- Streams real-time color-coded logs to console with service prefixes
- Writes individual service logs to `logs/{service}.log`
- Creates PID files for process management
- Runs health checks after services start

**Note**: If validation fails during startup, services will not start and you'll see clear error messages with troubleshooting steps.

**Parallel Startup Benefits:**
- Faster initialization (all services start at once)
- Real-time log aggregation with service identification
- Cross-platform compatibility (Windows, macOS, Linux)
- Automatic dependency management
- Graceful shutdown handling (Ctrl+C stops all services)

**Note**: Services handle their own dependency checks (e.g., backend waits for Redis/PostgreSQL). The parallel startup ensures faster initialization while maintaining service reliability.

### Restart Services

**Restart all services:**
```bash
# Linux/macOS:
./tools/commands/restart.sh

# Windows PowerShell:
.\tools\commands\restart.ps1
```

This will:
- Gracefully stop any running services
- Clear temporary state (local caches, stale pid files)
- Re-run the start command

### Health Check

**Check health of running services:**
```bash
python tools/commands/health_check.py
```

This verifies:
- Backend health endpoint responds
- Agent is responding (via backend)
- Frontend is accessible
- Individual service status (database, redis, agent)

### Audit Commands

**Run full quality gate:**
```bash
# Linux/macOS:
./tools/commands/audit.sh

# Windows PowerShell:
.\tools\commands\audit.ps1
```

The audit command executes:
- `ruff check` and `black --check` (Python style & lint)
- `pytest` (backend + agent unit tests)
- `npm test -- --watch=false` (frontend tests)
- Service health check (`curl http://localhost:8000/api/v1/health`)
- Log scan for warnings/errors (`grep -E "WARN|ERROR" logs/*.log`)

Output is written to `logs/audit/report.md` for review.

### Error Diagnostics

**Quick diagnostic for a running environment:**
```bash
# Linux/macOS:
./tools/commands/error.sh

# Windows PowerShell:
.\tools\commands\error.ps1
```

This will:
- Verify process status (backend, agent, frontend)
- Tail the last 200 lines of each service log
- Highlight new warnings/errors since the previous run

Output is written to `logs/error/summary.log` for later review.

---

## Step 9: Verify Installation

### 9.1 Check Backend Health

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
{
  "status": "healthy",
  "health_score": 0.95,
  "services": {
    "database": {"status": "up"},
    "redis": {"status": "up"},
    "agent": {"status": "up"}
  }
}
```

### 9.2 Check API Documentation

Open in browser: http://localhost:8000/docs

You should see the FastAPI interactive documentation.

### 9.3 Check Frontend

Open in browser: http://localhost:3000

You should see the JackSparrow dashboard.

### 9.4 Check Agent Status

```bash
curl http://localhost:8000/api/v1/admin/agent/status
```

Expected response should show agent state.

---

## Step 10: Upload ML Models (Optional)

### 10.1 Prepare Model Files

Place your trained model files in `agent/model_storage/custom/`:

```bash
# Example: Upload XGBoost model
cp my_xgboost_model.pkl agent/model_storage/custom/

# Create metadata
cat > agent/model_storage/custom/metadata.json << EOF
{
  "model_name": "my_xgboost_model",
  "model_type": "xgboost",
  "version": "1.0.0",
  "description": "Custom XGBoost model",
  "features_required": ["rsi_14", "macd_signal"]
}
EOF
```

### 10.2 Restart Agent

Restart the agent (Terminal 2) to discover new models:

```bash
# Stop agent (Ctrl+C)
# Restart agent
python -m agent.core.intelligent_agent
```

Check logs for model discovery messages.

### 10.3 Train Models (Alternative to Upload)

If you need to train new models or regenerate corrupted models, use the authoritative Colab notebook path for production-style BTCUSD artefacts:

- `notebooks/JackSparrow_Trading_Colab_v4.ipynb`

**Prerequisites**: Ensure Delta Exchange API credentials are configured in `.env`

Use script-based training only for legacy or experimental workflows.

**Legacy script path (optional)**:
```bash
# From project root
python scripts/train_models.py --symbol BTCUSD --timeframes 15m 1h 4h
```

**Validate Models**:
```bash
# Validate all models
python scripts/validate_model_files.py

# Or run pre-deployment validation
python scripts/validate_models_before_deployment.py
```

See [ML Models Documentation](03-ml-models.md#model-training) for detailed training guide.

**Post-train parity checklist (required before deployment)**:
1. Confirm `MODEL_DIR` points to the exact export folder that contains `metadata_BTCUSD_*.json`.
2. Confirm `metadata_*` includes `features` and `features_required` matching `feature_store/feature_registry.py` `EXPANDED_FEATURE_LIST` in order and count.
3. Run `pytest tests/unit/test_feature_parity.py -q`.

---

## Step 11: Run Tests (Optional)

### 11.1 Backend Tests

```bash
cd backend
source venv/bin/activate
pytest tests/unit/backend/ -v
```

### 11.2 Agent Tests

```bash
cd agent
source venv/bin/activate
pytest tests/unit/agent/ -v
```

### 11.3 Frontend Tests

```bash
cd frontend
npm test
```

---

## Troubleshooting

### Database Connection Issues

**Problem**: Cannot connect to PostgreSQL

**Solution**:
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list | grep postgresql  # macOS

# Verify connection string
psql -U trading_agent_user -d trading_agent -c "SELECT 1;"
```

### Redis Connection Issues

**Problem**: Cannot connect to Redis

**Solution**:
```bash
# Check Redis is running
redis-cli ping

# Start Redis if not running
sudo systemctl start redis  # Linux
brew services start redis  # macOS
```

### Port Already in Use

**Problem**: Port 8000 or 3000 already in use

**Solution**:
```bash
# Find process using port
lsof -i :8000  # Linux/macOS
netstat -ano | findstr :8000  # Windows

# Kill process or change port in configuration
```

### Module Import Errors

**Problem**: Python module not found

**Solution**:
```bash
# Verify virtual environment is activated
which python  # Should show venv path

# Reinstall dependencies
pip install -r requirements.txt
```

### Frontend Build Errors

**Problem**: Next.js build fails

**Solution**:
```bash
# Clear cache and reinstall
rm -rf node_modules .next
npm install
npm run build
```

### Validation Errors

**Problem**: Startup fails with validation errors

**Solutions**:
```bash
# Run individual validations to diagnose
python scripts/validate-env.py
python tools/commands/validate-prerequisites.py

# Common fixes:
# 1. Check .env file exists and has required variables
# 2. Verify DATABASE_URL format: postgresql://user:pass@host:port/db
# 3. Check API credentials: DELTA_EXCHANGE_API_KEY and SECRET
# 4. Ensure Python 3.11+ and Node.js 18+ are installed
# 5. Verify PostgreSQL and Redis are running
```

### Paper Trading Validation Failed

**Problem**: Startup blocked with paper trading safety warnings

**Solutions**:
```bash
# Check environment variables
echo $PAPER_TRADING_MODE
echo $TRADING_MODE

# Set safe paper trading mode
# Add to .env file:
PAPER_TRADING_MODE=true
TRADING_MODE=paper

# Remove any live trading configuration
# Remove or comment: TRADING_MODE=live
```

### Health Check Failures

**Problem**: Services start but health checks fail

**Solutions**:
```bash
# Run manual health check
python tools/commands/health_check.py

# Check detailed health status
python tools/commands/validate-health.py

# Common fixes:
# 1. Verify ports 8000, 8001, 3000 are available
# 2. Check database and Redis connectivity
# 3. Review service logs in logs/ directory
# 4. Restart services: stop then run startup again
```

---

## Quick Start Script

For convenience, create a startup script:

**`start-dev.sh`** (Linux/macOS):
```bash
#!/bin/bash

# Start Backend
cd backend
source venv/bin/activate
uvicorn api.main:app --reload --port 8000 &
BACKEND_PID=$!

# Start Agent
cd ../agent
source venv/bin/activate
python -m agent.core.intelligent_agent &
AGENT_PID=$!

# Start Frontend
cd ../frontend
npm run dev &
FRONTEND_PID=$!

echo "Services started:"
echo "Backend PID: $BACKEND_PID"
echo "Agent PID: $AGENT_PID"
echo "Frontend PID: $FRONTEND_PID"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for interrupt
trap "kill $BACKEND_PID $AGENT_PID $FRONTEND_PID; exit" INT
wait
```

**`start-dev.ps1`** (Windows PowerShell):
```powershell
# Start Backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\venv\Scripts\activate; uvicorn api.main:app --reload --port 8000"

# Start Agent
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd agent; .\venv\Scripts\activate; python -m agent.core.intelligent_agent"

# Start Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"
```

---

## Next Steps

After successful build:

1. **Configure Delta Exchange API**: Add your paper trading API keys
2. **Upload Models**: Place trained models in `agent/model_storage/` directory (organized by type, e.g., `agent/model_storage/xgboost/` for XGBoost models)
3. **Start Trading**: Use the dashboard or API to start the agent
4. **Monitor Performance**: Check dashboard for real-time updates
5. **Review Logs**: Check terminal outputs for debugging

---

## Related Documentation

- [Deployment Documentation](10-deployment.md) - Detailed setup instructions
- [Architecture Documentation](01-architecture.md) - System architecture
- [MCP Layer Documentation](02-mcp-layer.md) - MCP protocol details
- [ML Models Documentation](03-ml-models.md) - Model management
- [Backend Documentation](06-backend.md) - API documentation
- [Frontend Documentation](07-frontend.md) - Frontend documentation

---

## Build Verification Checklist

- [ ] PostgreSQL with TimescaleDB installed and running
- [ ] Redis installed and running
- [ ] Qdrant installed and running (optional)
- [ ] Backend virtual environment created
- [ ] Backend dependencies installed
- [ ] Backend environment variables configured
- [ ] Database initialized
- [ ] Agent virtual environment created
- [ ] Agent dependencies installed
- [ ] Agent environment variables configured
- [ ] Model storage directories created
- [ ] Frontend dependencies installed
- [ ] Frontend environment variables configured
- [ ] Backend starts successfully
- [ ] Agent starts successfully
- [ ] Frontend starts successfully
- [ ] Health check endpoint responds
- [ ] API documentation accessible
- [ ] Dashboard accessible
- [ ] All services communicate properly

If all items are checked, your build is complete and ready for development!

