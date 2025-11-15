# JackSparrow

> **AI-Powered Trading Agent for Delta Exchange India Paper Trading**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

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
# Start all services
make start

# Restart services
make restart

# Run audit
make audit

# Check for errors
make error
```

### Environment Setup

1. Copy `.env.example` files to `.env` in `backend/` and `agent/` directories
2. Configure database, Redis, and Delta Exchange API credentials
3. See [Deployment Documentation](docs/10-deployment.md) for details

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

