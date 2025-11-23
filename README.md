# JackSparrow

> **AI-Powered Trading Agent for Delta Exchange India Paper Trading**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

> For the pirates who love treasure hunting, except for the fact that there is no water here. The treasure is sought out of thin air.

## Overview

JackSparrow is a functional AI-powered trading agent (not just a bot) that:
1. **Autonomously analyzes** market data using ML models
2. **Makes intelligent decisions** based on multi-model consensus
3. **Executes trades** with proper risk management
4. **Learns and adapts** from trading outcomes
5. **Communicates status** clearly through integrated interfaces

## Key Requirements

- **Paper trading only** on Delta Exchange India (BTCUSD initially)
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
# Start all services (parallel startup - faster!)
make start
# or directly:
python tools/commands/start_parallel.py

# Restart services
make restart

# Run audit
make audit

# Check for errors
make error
```

**Note**: The startup system uses a Python-based parallel process manager that starts all services (backend, agent, frontend) simultaneously, providing faster initialization and real-time log streaming. See [Deployment Documentation](docs/10-deployment.md) for details.

## Containerized Deployment

All 24/7 services now run via Docker images orchestrated with Compose.

1. Copy/create the `.env` files described below and set secrets consumed during build/test/deploy (minimum: `DELTA_EXCHANGE_API_KEY`, `DELTA_EXCHANGE_API_SECRET`, `JWT_SECRET_KEY`, `API_KEY`, `POSTGRES_PASSWORD`).
2. Prepare persistent host paths before the first deployment:
   ```bash
   mkdir -p logs/backend logs/agent logs/frontend models
   touch kubera_pokisham.db
   ```
3. Build and start the stack:
   ```bash
   docker compose up --build -d
   ```
4. Inspect status & logs:
   ```bash
   docker compose ps
   docker compose logs -f backend
   ```

The stack provisions TimescaleDB/PostgreSQL, Redis, the AI agent (feature server on `8001`), FastAPI backend (`8000`), and Next.js frontend (`3000`). Named volumes keep Postgres and Redis durable, while bind mounts (`./models`, `./logs/*`, `./kubera_pokisham.db`) keep artifacts accessible on the host.

## CI/CD Pipeline

GitHub Actions workflow [`cicd.yml`](.github/workflows/cicd.yml) runs backend/agent pytest suites, executes `npm test -- --ci` for the frontend, builds Docker images for each service, pushes them to GHCR on `main`, and redeploys the Compose stack via SSH. Required repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`, and `DEPLOY_PATH`. See [Deployment Documentation](docs/10-deployment.md#cicd-automation) for setup details.

### Environment Setup

1. **Create `.env` files**:
   - Copy `backend/.env.example` to `backend/.env` (or create from template in `backend/core/config.py`)
   - Copy `agent/.env.example` to `agent/.env` (or create from template in `agent/core/config.py`)
   - Copy `frontend/.env.example` to `frontend/.env.local` (optional, defaults provided)
2. **Configure required variables**:
   - `DATABASE_URL` - PostgreSQL connection string
   - `DELTA_EXCHANGE_API_KEY` and `DELTA_EXCHANGE_API_SECRET` - Delta Exchange credentials
   - `JWT_SECRET_KEY` and `API_KEY` - Security keys (backend only)
   - *(Optional)* `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` - Enable Telegram trade alerts
3. **Initialize database**: Run `python scripts/setup_db.py` before starting services
4. See [Deployment Documentation](docs/10-deployment.md) for complete details

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

```
JackSparrow/
├── backend/          # FastAPI backend API
├── agent/            # AI agent core with MCP layer
├── frontend/         # Next.js frontend dashboard
├── tests/            # Test suite
├── scripts/          # Utility scripts
├── tools/            # Command toolkit
├── docs/             # Documentation
├── models/           # Production ML models
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

### Testing

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
