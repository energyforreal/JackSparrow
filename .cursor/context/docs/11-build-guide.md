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

**Option 1: Use .env.example template (recommended)**
```bash
# Copy the example file
cp backend/.env.example backend/.env

# Edit backend/.env with your actual values
# Required variables:
#   - DATABASE_URL
#   - DELTA_EXCHANGE_API_KEY
#   - DELTA_EXCHANGE_API_SECRET
#   - JWT_SECRET_KEY
#   - API_KEY
```

**Option 2: Create manually**
Create `backend/.env` with the following required variables:

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://trading_agent_user:your_password@localhost:5432/trading_agent

# Redis (default: redis://localhost:6379)
REDIS_URL=redis://localhost:6379

# Delta Exchange (REQUIRED - Paper Trading)
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret
DELTA_EXCHANGE_BASE_URL=https://api.delta.exchange

# Security (REQUIRED)
JWT_SECRET_KEY=your_secret_key_here_minimum_32_characters
API_KEY=your_api_key_here_minimum_32_characters

# Agent Communication (defaults provided)
AGENT_COMMAND_QUEUE=agent_commands
AGENT_RESPONSE_QUEUE=agent_responses

# Feature Server (default: http://localhost:8001)
FEATURE_SERVER_URL=http://localhost:8001

# Vector Database (Optional)
QDRANT_URL=
QDRANT_API_KEY=

# Logging (default: INFO)
LOG_LEVEL=INFO
```

**Note**: If `.env.example` files don't exist, refer to `backend/core/config.py` and `agent/core/config.py` for all available configuration options and their descriptions.

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
- Check DATABASE_URL in `backend/.env` is correct

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

**Note**: The root `models/` directory already contains production models. The `agent/model_storage/` directory is for uploading new or custom models.

```bash
# Create upload directory for custom models (if you plan to upload models)
mkdir -p agent/model_storage/custom
mkdir -p agent/model_storage/xgboost
mkdir -p agent/model_storage/lstm
mkdir -p agent/model_storage/transformer
```

### 6.4 Configure Environment Variables

**Option 1: Use .env.example template (recommended)**
```bash
# Copy the example file
cp agent/.env.example agent/.env

# Edit agent/.env with your actual values
# Required variables:
#   - DATABASE_URL
#   - DELTA_EXCHANGE_API_KEY
#   - DELTA_EXCHANGE_API_SECRET
```

**Option 2: Create manually**
Create `agent/.env` with the following required variables:

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://trading_agent_user:your_password@localhost:5432/trading_agent

# Redis (default: redis://localhost:6379)
REDIS_URL=redis://localhost:6379

# Delta Exchange (REQUIRED - Paper Trading)
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret
DELTA_EXCHANGE_BASE_URL=https://api.delta.exchange

# Vector Database (Optional)
QDRANT_URL=
QDRANT_API_KEY=

# Model Configuration
# Option 1: Use production model from root models/ directory (recommended for initial setup)
# MODEL_PATH=models/xgboost_BTCUSD_15m.pkl  # Uncomment to use production model

# Option 2: Use model discovery for uploaded models in agent/model_storage/
MODEL_DIR=./agent/model_storage
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true

# Agent Configuration (defaults provided)
AGENT_START_MODE=MONITORING
AGENT_SYMBOL=BTCUSD
AGENT_INTERVAL=15m

# Risk Management (defaults provided)
MAX_POSITION_SIZE=0.1
MAX_PORTFOLIO_HEAT=0.3
STOP_LOSS_PERCENTAGE=0.02
TAKE_PROFIT_PERCENTAGE=0.05

# Logging (default: INFO)
LOG_LEVEL=INFO
```

**Note**: If `.env.example` files don't exist, refer to `agent/core/config.py` for all available configuration options and their descriptions.

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

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
```

### 7.3 Verify Frontend Setup

```bash
npm run build
# Should complete without errors
```

---

## Step 8: Start Services

You'll need **three separate terminal windows** for this step.

### 8.1 Terminal 1: Start Backend

```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn api.main:app --reload --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### 8.2 Terminal 2: Start Agent

```bash
cd agent
source venv/bin/activate  # On Windows: venv\Scripts\activate
python -m agent.core.intelligent_agent
```

Expected output:
```
INFO: Agent initialized
INFO: Model discovery started
INFO: Models registered: XGBoost, LSTM, Transformer
INFO: Agent ready
```

### 8.3 Terminal 3: Start Frontend

```bash
cd frontend
npm run dev
```

Expected output:
```
- ready started server on 0.0.0.0:3000
- Local:        http://localhost:3000
```

### 8.4 Smoke Test Checklist

After all three terminals report successful startup:

1. Visit `http://localhost:3000` and confirm the dashboard renders without console errors.
2. Open `http://localhost:8000/api/v1/health` in a second tab—health score should be ≥ `0.90` when all components are healthy.
3. Trigger a manual prediction with `curl -X POST http://localhost:8000/api/v1/predict -d '{}' -H 'Content-Type: application/json'` and verify the response arrives in the dashboard.
4. Inspect `logs/start.log` for any WARN/ERROR entries; resolve before continuing development.

---

## Project Commands
The project root contains a `Makefile` with convenience commands that orchestrate the full JackSparrow stack. Run these commands from the repository root (`JackSparrow/`).

### `make start`
- Launches backend (`uvicorn`), agent (`python -m agent.core.intelligent_agent`), and frontend (`npm run dev`) **simultaneously** using parallel process manager
- Automatically sets up virtual environments and installs dependencies if needed
- Streams real-time color-coded logs to console with service prefixes
- Writes individual service logs to `logs/{service}.log`
- Creates PID files for process management

```bash
make start
# or directly:
python tools/commands/start_parallel.py
```

**Parallel Startup Benefits:**
- Faster initialization (all services start at once)
- Real-time log aggregation with service identification
- Cross-platform compatibility (Windows, macOS, Linux)
- Automatic dependency management
- Graceful shutdown handling (Ctrl+C stops all services)

**Note**: Services handle their own dependency checks (e.g., backend waits for Redis/PostgreSQL). The parallel startup ensures faster initialization while maintaining service reliability.

### `make restart`
- Gracefully stops any running services (`make stop`)
- Clears temporary state (local caches, stale pid files)
- Re-runs `make start`

```bash
make restart
```

### `make audit`
- Runs full quality gate: formatting, linting, tests, and service health checks
- Captures recent service logs (backend, agent, frontend) to `logs/audit/`
- Summarises findings to the console and writes a report to `logs/audit/report.md`

```bash
make audit
```

The audit command executes:
- `ruff check` and `black --check` (Python style & lint)
- `pytest` (backend + agent unit tests)
- `npm test -- --watch=false` (frontend tests)
- Service health check (`curl http://localhost:8000/api/v1/health`)
- Log scan for warnings/errors (`grep -E "WARN|ERROR" logs/*.log`)

### `make error`
- Quick diagnostic for a running environment
- Verifies process status (backend, agent, frontend)
- Tails the last 200 lines of each service log
- Highlights new warnings/errors since the previous run

```bash
make error
```

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

Use script-based training only for legacy or experimental workflows.

**Legacy script path (optional)**:
```bash
# From project root
python scripts/train_models.py --symbol BTCUSD --timeframes 15m 1h 4h
```

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
2. **Upload Models**: Place trained models in `agent/model_storage/custom/` (for model discovery) or copy to root `models/` directory (for production use)
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

