# JackSparrow

> **AI-Powered Trading Agent for Delta Exchange India Testnet**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

> For the pirates who love treasure hunting, except for the fact that there is no water here. The treasure is sought out of thin air.

## Overview

JackSparrow is a functional AI-powered trading agent (not just a bot) that:

1. **Autonomously analyzes** market data using ML models (as **supporting evidence**, not sole authority)
2. **Decides under agent policy** — ML consensus and gates inform an explicit policy verdict before any `DECISION_READY` trade intent
3. **Executes trades** only after risk validation and execution gates
4. **Learns and adapts** from trading outcomes
5. **Communicates status** clearly through integrated interfaces

## Key Requirements

- **Delta testnet trading only** (real testnet orders on Delta Exchange India; BTCUSD initially)
- **INR portfolio defaults**: `INITIAL_BALANCE=20000` (displayed as `₹20,000`)
- **Currency split**: BTCUSD market prices render in `USD ($)` while portfolio/PnL render in `INR (₹)`
- **Entry confidence gate**: trades execute only when confidence is `>= 70%` (`MIN_CONFIDENCE_THRESHOLD=0.70`)
- **v43 execution tuning**: see [docs/v43_trade_execution_runbook.md](docs/v43_trade_execution_runbook.md) (gate 5 ratio, debounce, shorts, trending trial, log analysis)
- **Delta BTCUSD lot semantics**: `MIN_LOT_SIZE=1` lot with `CONTRACT_VALUE_BTC=0.001` (1 lot = 0.001 BTC)
- **Runtime execution controls**: fixed `1` lot entries, isolated margin assumption `5x`, INR margin sufficiency checks
- **Real-time price monitoring** with instant BTCUSD price updates in frontend
- **Fluctuation-based signal generation** triggered when price moves exceed `PRICE_FLUCTUATION_THRESHOLD_PCT` (default **0.10** = 0.10%; configurable in `.env`, e.g. `0.5` for 0.5%)
- **Reliable frontend-backend integration** with real-time communication
- **True AI agent behavior** with autonomous decision-making capabilities
- **Comprehensive monitoring** with health checks and degradation detection
- **Production-ready code** with proper error handling and logging

## Technology Stack

- **Backend**: FastAPI, Python 3.11+, PostgreSQL with TimescaleDB, Redis
- **AI/ML**: XGBoost, LightGBM, TensorFlow (LSTM/Transformer), SHAP
- **Frontend**: Next.js 14+, TypeScript, Tailwind CSS
- **Vector Storage**: Qdrant or Pinecone
- **Monitoring**: Prometheus + Grafana, Structured logging

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ with TimescaleDB
- Redis 7.0+

### Installation

See [Build Guide](docs/11-build-guide.md) for complete step-by-step instructions.

**Quick Start Commands:**

```bash
# Validate configuration and prerequisites (recommended before starting)
python tools/commands/validate-prerequisites.py

# Start all services (parallel startup - faster!)
# The startup script automatically validates configuration and prerequisites before starting
python tools/commands/start_parallel.py

# Alternative startup methods:
# Linux/macOS:
./tools/commands/start.sh

# Windows PowerShell:
.\tools\commands\start.ps1

# Check health of running services
  python tools/commands/health_check.py

# Restart services: Stop services (Ctrl+C) then run start command again
```

#### Startup Sequence

The `start_parallel.py` script performs a comprehensive 4-step startup sequence:

1. **Environment Loading**: Loads and validates environment configuration
2. **Paper Trading Validation**: Verifies safe paper trading mode (blocks live trading)
3. **Redis Availability**: Ensures Redis service is available and starts it if needed
4. **Configuration Validation**: Runs environment variable and prerequisite validation
5. **Optional Model Validation**: Validates ML model files if `VALIDATE_MODELS_ON_STARTUP=true`
6. **Service Dependencies**: Ensures all dependencies are properly set up
7. **Parallel Startup**: Starts backend, agent, and frontend services simultaneously
8. **Health Checks**: Performs post-startup health verification
9. **Monitoring Dashboard**: Launches real-time monitoring with data freshness tracking

**Note**: The startup script (`start_parallel.py`) automatically validates your configuration and prerequisites before starting services and runs health checks after services start. If validation fails, startup will stop with clear error messages. It's recommended to run validation manually first to catch issues early.

**Note**: The startup system uses a Python-based parallel process manager that starts all services (backend, agent, frontend) simultaneously, providing faster initialization and real-time log streaming. See [Deployment Documentation](docs/10-deployment.md) for details.

### Delta Testnet Validation

**JackSparrow** runs exclusively on **Delta Exchange India testnet** (real testnet orders; local paper simulation removed):

- **Startup validation**: `TRADING_MODE=testnet`, `DELTA_ENV=india_testnet`, and testnet REST/WebSocket URLs are enforced
- **Rejected settings**: `PAPER_TRADING_MODE`, `EXCHANGE_BACKEND=delta_paper_sim`, and production Delta hosts fail fast at startup
- **Safety indicators**: The monitoring dashboard shows testnet mode and exchange health

**Required testnet profile** (see `.env.example`):

```bash
TRADING_MODE=testnet
DELTA_ENV=india_testnet
EXCHANGE_BACKEND=delta_live
DELTA_EXCHANGE_BASE_URL=https://cdn-ind.testnet.deltaex.org
WEBSOCKET_URL=wss://socket-ind.testnet.deltaex.org
```

REST uses the **CDN host** (`cdn-ind`); market **WebSocket** uses the **socket host** (`socket-ind`). Compose sets `WEBSOCKET_URL` when unset. Whitelist your host egress IP in Delta testnet API settings if private-channel auth is rejected.

### Monitoring Dashboard

The startup system includes a real-time monitoring dashboard that provides:

- **Service Status**: Real-time health monitoring of backend, agent, and frontend services
- **Testnet Status**: Clear indicators showing Delta testnet trading mode
- **WebSocket Monitoring**: Automatic connection monitoring and message freshness tracking
- **Data Freshness**: Per-message type freshness scores and stale message detection
- **Signal Generation Statistics**: Frequency analysis and last signal tracking
- **Overall Health Score**: Comprehensive system health assessment

The monitoring dashboard updates every 2 seconds and provides immediate visibility into system operation.

## Containerized Deployment

All 24/7 services now run via Docker images orchestrated with Compose.

1. Copy/create the root `.env` file: `cp .env.example .env` and set secrets consumed during build/test/deploy (minimum: `DELTA_EXCHANGE_API_KEY`, `DELTA_EXCHANGE_API_SECRET`, `JWT_SECRET_KEY`, `API_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — keep `REDIS_URL` in sync so it includes the same password). All services read from this single root `.env` file.

2. Prepare persistent host paths before the first deployment:

   ```bash
   mkdir -p logs/backend logs/agent logs/frontend agent/model_storage/JackSparrow_IC_BTCUSD
   ```

3. Build and start the stack:

   ```bash
   docker compose build --pull
   docker compose up -d --force-recreate
   ```

   Optional Qdrant (vector store profile — not required for default IC mode):

   ```bash
   docker compose --profile full up -d --force-recreate
   ```

   For local development with hot reload and exposed agent ports `8002`/`8003`:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
   ```

   If the frontend image was still building when `up` ran, pick up the latest tag with `docker compose up -d --force-recreate frontend`.

4. Inspect status & logs:

   ```bash
   docker compose ps
   docker compose logs -f backend
   ```

The stack provisions TimescaleDB/PostgreSQL, Redis, the AI agent (feature HTTP on **`:8002`** and command WebSocket on **`:8003`** inside the Docker network), FastAPI backend (`8000` on the host), and Next.js frontend (`3000` on the host). Named volumes keep Postgres and Redis durable; bind mounts keep **`./agent/model_storage`** and **`./logs/*`** on the host. Application source is **baked into images** in production — rebuild after code changes. Agent ports are **not** published on the host unless you use **`docker-compose.dev.yml`**.

## Intelligence Component (NO-ML default)

Inference uses the **rule-based Intelligence Component (IC)** — no pickle load at runtime:

- **`MODEL_DIR`** → **`agent/model_storage/JackSparrow_IC_BTCUSD/`** (must contain **`metadata_ic.json`** only).
- **`IC_MODE=true`**, **`AGENT_POLICY_MODE=ml_or_thesis`**, **`REQUIRE_ML_SIGNAL_FOR_ORDERS=false`** (see [.env.example](.env.example)).
- Features: same v43 contract (`feature_store/jacksparrow_v43_contract.py`), built by **`jacksparrow_v43_build_matrix.py`**, scored by **`agent/intelligence/`** modules.

Docker Compose defaults **`MODEL_DIR`** from **`AGENT_MODEL_DIR`** to **`/app/agent/model_storage/JackSparrow_IC_BTCUSD`** and sets **`WEBSOCKET_URL`** to **`wss://socket-ind.testnet.deltaex.org`** when unset.

Archived **v43 XGBoost** bundles and training notebooks are documented under **[ML models – archived v43](docs/03-ml-models.md#archived-jacksparrow-v43-xgboost--mso-v50)**. Historical **v15** / **v5** artefacts may remain for parity tests and optional **v15 parquet adaptive retrain** only.

See [ML Models Documentation](docs/03-ml-models.md) for discovery, Docker bundle layout, and troubleshooting.

## Testing

The project includes comprehensive test suites and validation scripts. See [Build Guide – Tests and verification](docs/11-build-guide.md#tests-and-verification).

### Quick Test Commands

```bash
# Run all fix-related tests
python tools/commands/run-fix-tests.py

# Validate all fixes are in place
python tools/commands/validate-fixes.py

# Test Unicode encoding handling
python tools/commands/test-encoding.py

# Test startup sequence
python tools/commands/test-startup-sequence.py

# Run health checks
  python tools/commands/health_check.py

# Enhanced health validation
python tools/commands/validate-health.py
```

### Test Categories

- **Unit Tests**: Component-level tests in `tests/unit/`
- **Integration Tests**: System integration tests in `tests/integration/`
- **Validation Scripts**: Fix validation and system checks
- **Monitoring**: Continuous health monitoring

See [Build Guide](docs/11-build-guide.md) and [Debugging](docs/13-debugging.md) for detailed information.

### Common Startup Issues

The startup script provides clear error messages for common issues:

- **Testnet Validation Failed**: Check `TRADING_MODE=testnet`, `DELTA_ENV=india_testnet`, and testnet Delta API URLs/keys
- **Environment Validation Failed**: Re-run `python tools/commands/validate-prerequisites.py` and review startup logs for missing `.env` values
- **Prerequisite Validation Failed**: Run `python tools/commands/validate-prerequisites.py` to check Python, Node.js, PostgreSQL, Redis
- **Model Validation Failed**: Check ML model files or disable with `VALIDATE_MODELS_ON_STARTUP=false`

For detailed troubleshooting, see [Debugging](docs/13-debugging.md) and [Deployment](docs/10-deployment.md#troubleshooting).

## CI/CD Pipeline

GitHub Actions workflow [`cicd.yml`](.github/workflows/cicd.yml) runs backend/agent pytest suites, executes `npm test -- --ci` for the frontend, builds Docker images for each service, pushes them to GHCR on `main`, and redeploys the Compose stack via SSH. Required repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`, and `DEPLOY_PATH`. See [Deployment Documentation](docs/10-deployment.md#cicd-automation) for setup details.

### Environment Setup

1. **Create root `.env` file**:
   - `.env.example` (committed) holds **non-secret defaults**: ports, thresholds, feature flags, public URLs, model paths.
   - Create a root `.env` with **secrets only** (gitignored): DB password, Delta API key/secret, `JWT_SECRET_KEY`, `API_KEY`, `REDIS_PASSWORD`, optional Qdrant/Telegram tokens, and any personal overrides.
   - Loaders merge them as `.env.example` first, then `.env` on top (real OS env wins over both). All services (backend, agent, frontend, Docker Compose) read the same two root files.
2. **Required secrets** in root `.env`:
   - `DATABASE_URL` (PostgreSQL URL with real password) and `POSTGRES_PASSWORD`
   - `REDIS_PASSWORD` (and full `REDIS_URL` if you want non-default Redis auth)
   - `DELTA_EXCHANGE_API_KEY` and `DELTA_EXCHANGE_API_SECRET`
   - `JWT_SECRET_KEY` and `API_KEY` (>= 32 chars each)
   - *(Optional)* `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `QDRANT_API_KEY`
3. **Initialize database**: Follow the DB setup steps in [Build Guide](docs/11-build-guide.md).
4. See [Deployment Documentation](docs/10-deployment.md) for complete details.

**Note**: Use only the project root for environment files. Do **not** add `agent/.env`, `backend/.env`, or `frontend/.env(.local)`. Python services read via Pydantic's `env_file=(.env.example, .env)` tuple in `agent/core/config.py` and `backend/core/config.py`; the frontend reads both via `loadRootEnv()` in `next.config.js`; Docker Compose lists both files under each service's `env_file:`.

## Documentation

Comprehensive documentation is available in the `docs/` directory:

- [Architecture Documentation](docs/01-architecture.md) - System design
- [MCP Layer Documentation](docs/02-mcp-layer.md) - MCP protocol details
- [ML Models Documentation](docs/03-ml-models.md) - Model management
- [Build Guide](docs/11-build-guide.md) - Complete build instructions
- [API Documentation](docs/06-backend.md) - Backend API reference
- [Frontend Documentation](docs/07-frontend.md) - Frontend implementation

See [DOCUMENTATION.md](DOCUMENTATION.md) for the complete index.

## Project Structure

```text
JackSparrow/
├── backend/          # FastAPI backend API
├── agent/            # AI agent core with MCP layer
│   └── model_storage/ # Trained bundles (e.g. jacksparrow_v5_*); see docs/03-ml-models.md
├── frontend/         # Next.js frontend dashboard
├── tests/            # Test suite
├── scripts/          # Utility scripts
├── tools/            # Command toolkit
├── docs/             # Documentation
└── logs/             # Application logs
```

## Development

### Running Services

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn api.main:app --reload --port 8000

# Terminal 2: Agent
cd agent
source venv/bin/activate
python -m agent.core.intelligent_agent

# Terminal 3: Frontend
cd frontend
npm run dev
```

### Development Testing

```bash
# Backend tests
cd backend && pytest

# Agent tests
cd agent && pytest

# Frontend tests
cd frontend && npm test
```

## Contributing

Please read [Project Rules](docs/14-project-rules.md) before contributing.

## License

See [LICENSE](LICENSE) file for details.

## Support

- **Documentation**: See [DOCUMENTATION.md](DOCUMENTATION.md)
- **Issues**: [GitHub Issues](https://github.com/energyforreal/JackSparrow/issues)
