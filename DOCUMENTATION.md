# JackSparrow Documentation

> **AI-Powered Trading Agent for Delta Exchange India Paper Trading**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

This document serves as the central index for all project documentation. Navigate to specific sections using the links below.

---

## 📚 Documentation Index

### Core Documentation

1. **[Architecture Documentation](docs/01-architecture.md)**
   - System architecture overview
   - Three-tier architecture (Data → Intelligence → Presentation)
   - MCP protocol integration and orchestration
   - Component definitions and integration points
   - Communication protocols and error handling

2. **[MCP Layer Documentation](docs/02-mcp-layer.md)**
   - Custom MCP (Model Context Protocol) layer architecture
   - MCP Feature Protocol implementation
   - MCP Model Protocol and model registry
   - MCP Reasoning Protocol and reasoning engine
   - MCP orchestration and component interaction
   - Integration points and error handling

3. **[ML Models Documentation](docs/03-ml-models.md)**
   - ML model directory structure and organization
   - Model upload process and directory location
   - Model discovery and registration mechanism
   - AI agent intelligence for model interaction
   - Model type detection and understanding
   - Model versioning and management
   - Price prediction models with pagination and data reversal support
   - Currently integrated: **v5 BTCUSD entry/exit ensembles** — five timeframe nodes (15m–4h); see [Model Integration Summary](docs/model-integration-summary.md)
   - **[ML Training Guide - Google Colab](docs/ml-training-google-colab.md)** - Comprehensive guide for training models in Google Colab
   - **[Colab Quick Start](docs/colab-quick-start.md)** - Short path into Colab training workflows
   - **[Training and Feature Parity](docs/training-and-feature-parity.md)** - Authoritative notebook path, parity checklist, and HOLD-context guidance
   - **[Model Integration Summary](docs/model-integration-summary.md)** - Current model bundle layout, `MODEL_DIR`, and discovery contract

4. **[Features Documentation](docs/04-features.md)**
   - Core trading agent features
   - AI reasoning capabilities
   - Multi-model ensemble system
   - Learning and adaptation mechanisms
   - Risk management features
   - Real-time monitoring capabilities

5. **[Logic & Reasoning Documentation](docs/05-logic-reasoning.md)**
   - Agent reasoning engine architecture
   - 6-step reasoning chain process
   - MCP Reasoning Engine integration
   - Decision-making framework
   - Model consensus mechanism
   - Model intelligence and interaction
   - Learning algorithms
   - Confidence calibration system

### Implementation Documentation

- **[Trading Agent Improvements Implementation](docs/trading-agent-improvements-implementation.md)** – Summary of improvements from the trading agent improvement report (WebSocket SL/TP, Kelly sizing, signal-reversal exit, trailing stop, learning feedback, etc.) with code references.
- **[Data Exchange Implementation Notes](docs/data-exchange-implementation-notes.md)** – Data flow between frontend, backend, and agent; confidence/signal format conventions; event deduplication and position-closed handling.

6. **[Backend Documentation](docs/06-backend.md)**
   - FastAPI application structure
   - REST API endpoints specification
   - WebSocket implementation
   - Database models and schemas
   - Service layer architecture
   - Health checks and monitoring
   - MCP layer integration

7. **[Frontend Documentation](docs/07-frontend.md)**
   - Next.js application structure
   - **`useTradingData`** as the unified dashboard state hook (replaces ad-hoc `switch` on `lastMessage` in `Dashboard`)
   - Dashboard UX: skeleton loaders, trade toasts (`react-hot-toast`), tab title price, keyboard **P** for prediction, and related polish (see *Dashboard UX enhancements*)
   - WebSocket integration (simplified format)
   - Real-time update mechanisms
   - UI component specifications
   - **[WebSocket Simplification Guide](docs/WEBSOCKET_SIMPLIFICATION.md)** - Simplified WebSocket communication format

8. **[File Structure Documentation](docs/08-file-structure.md)**
   - Complete project directory structure
   - File organization principles
   - Module responsibilities
   - Code organization patterns
   - ML model storage structure

### Design & Deployment

9. **[UI/UX Documentation](docs/09-ui-ux.md)**
   - Dashboard design specifications
   - Loading skeletons, empty states, and trade toasts
   - Component design guidelines (e.g. strong-signal pulse on **STRONG_BUY** / **STRONG_SELL**)
   - User interaction flows
   - Visual design system
   - Responsive design patterns
   - Accessibility considerations

10. **[Deployment Documentation](docs/10-deployment.md)**
    - Development environment setup
    - Local runtime execution
    - Next.js webapp setup and execution
    - Testing environment configuration
    - Environment variables
    - Database setup and migrations
    - Docker deployment: `docker compose build --pull` and `up -d --force-recreate` for full rebuilds; optional `frontend`-only recreate after image build
    - Monitoring and observability setup
    - Troubleshooting guide

11. **[Docker Hot Reload Guide](docs/docker-hot-reload.md)**
    - Hot reload setup and configuration
    - How hot reload works for each service
    - Usage examples and best practices
    - Troubleshooting hot reload issues
    - Related: [Quick Reference](docs/docker-hot-reload-quick-reference.md), [Implementation Summary](docs/docker-hot-reload-implementation-summary.md), [Testing Guide](docs/docker-hot-reload-testing-guide.md)

12. **[Build Guide](docs/11-build-guide.md)**
    - Complete step-by-step build instructions
    - Project setup from scratch
    - Prerequisites and dependencies
    - Executable commands for building entire project
    - Verification steps for each component
    - Quick start scripts

### Operations & Observability

12. **[Logging Documentation](docs/12-logging.md)**
    - Centralized logging architecture
    - Service-wide error capture strategy
    - Log rotation and startup clearing
    - Log transport and storage options
    - Observability integrations
    - Operational procedures and SLIs
13. **[Docker Runtime Architecture](docs/docker-runtime-architecture.md)**
    - Runtime behaviour of the dockerized stack
    - Container roles and network topology
    - Real-time communication and data flows
    - Docker engine logs vs application logs
    - Operator investigation recipes

14. **[Debugging & Error Handling Guide](docs/13-debugging.md)**
    - Development-time debugging workflows
    - Enabling debug modes per service
    - Using structured logs for triage
    - Common failure reproduction steps
    - Incident response checklist
    - Tooling and best practices

### Project Standards

14. **[Project Rules Documentation](docs/14-project-rules.md)**
   - Coding standards and conventions
   - Git workflow and branching strategy
   - Naming conventions
   - Documentation standards
   - Testing requirements
   - Code review process

### Audit & Quality

15. **[Audit Report](docs/15-audit-report.md)**
   - Documentation audit findings
   - Gap analysis against reference specifications
   - Missing features identification
   - Update recommendations

16. **[Audit Findings](docs/archive/audit-findings-2025-11-18.md)** (Archived)
   - Initial project audit findings
   - Critical issues identified
   - Medium priority issues
   - Recommendations and next steps
   - Note: See [Comprehensive Audit Report](docs/comprehensive-audit-report.md) for current status

17. **[Comprehensive Audit Report](docs/comprehensive-audit-report.md)**
   - Complete full-stack audit report
   - All critical, high, medium, and low priority issues
   - Resolution status tracking
   - Testing recommendations

18. **[Docker Logs Analysis Reports](docs/docker-logs-analysis-report-current.md)**
   - Container health analysis
   - Service-specific issue identification
   - Docker deployment troubleshooting
   - Latest 8h AI/signals review: [Docker Logs Analysis Report — 2026-03-23](docs/docker-logs-analysis-report-20260323.md)
   - Related: [Docker Logs Follow-up Report](docs/archive/docker-logs-followup-report-2025-11-20.md), [Docker Logs Analysis Report - 2025-11-23](docs/archive/docker-logs-analysis-report-2025-11-23.md)

19. **[Remediation Plan](docs/remediation-plan.md)**
   - Step-by-step remediation for identified issues
   - Implementation priorities
   - Testing checklists
   - Rollback procedures

20. **Archived time-stamped reports (`docs/archive/`)**
    - Historical audit outputs and log-analysis snapshots
    - Kept for reference only; can be regenerated or pruned as needed

### Narrative & change history

- **[Major Changes Summary](docs/major-changes.md)** — Architectural overhaul and production-readiness changelog (2025-01-27 baseline)
- **[Project Comprehensive Documentation](docs/project-comprehensive-documentation.md)** — Long-form narrative archive; prefer numbered `docs/01-*.md` … `docs/11-*.md` for day-to-day maintenance

### Reports (`docs/reports/`)

Deep-dive and historical reports (non-canonical; useful for context):

- [System audit report 2025](docs/reports/system-audit-report-2025.md) — Full-stack paper-trading audit (distinct from [documentation audit](docs/15-audit-report.md))
- [JackSparrow ML redesign report](docs/reports/jacksparrow-ml-redesign-report.md)
- [JackSparrow reworked report](docs/reports/jacksparrow-reworked-report.md)
- [ML pipeline and dataflow report](docs/reports/ml-pipeline-and-dataflow-report.md)
- [ML pipeline enhancement proposal](docs/reports/ml-pipeline-enhancement-proposal.md)
- [Exit models training report](docs/reports/exit-models-training-report.md)
- [Trading agent improvement report](docs/reports/trading-agent-improvement-report.md)
- [JackSparrow implementation analysis](docs/reports/jacksparrow-implementation-analysis.md)

### Cursor IDE (`docs/cursor/`)

- [Auto-approve setup](docs/cursor/auto-approve-setup.md)
- [Settings quick fix](docs/cursor/settings-quick-fix.md)

---

## 🎯 Project Overview

### Core Mission

Build a functional AI-powered trading agent (not just a bot) that:
1. **Autonomously analyzes** market data using ML models
2. **Makes intelligent decisions** based on multi-model consensus
3. **Executes trades** with proper risk management
4. **Learns and adapts** from trading outcomes
5. **Communicates status** clearly through integrated interfaces

### Key Requirements

- **Paper trading only** on Delta Exchange India (BTCUSD initially)
- **Reliable frontend-backend integration** with real-time communication
- **True AI agent behavior** with autonomous decision-making capabilities
- **Comprehensive monitoring** with health checks and degradation detection
- **Production-ready code** with proper error handling and logging

### Technology Stack

- **Backend**: FastAPI, Python 3.11+, PostgreSQL with TimescaleDB, Redis
- **AI/ML**: XGBoost, LightGBM, TensorFlow (LSTM/Transformer), SHAP
- **Frontend**: Next.js 14+, TypeScript, Tailwind CSS
- **Vector Storage**: Qdrant or Pinecone
- **Monitoring**: Prometheus + Grafana, Structured logging

---

## 🚀 Quick Start

**To build and run the entire project**, follow the [Build Guide](docs/11-build-guide.md) which provides step-by-step instructions to set up everything from scratch.

**For understanding the system**:
1. **Read Architecture**: Start with [Architecture Documentation](docs/01-architecture.md) to understand the system design
2. **Understand MCP Layer**: Review [MCP Layer Documentation](docs/02-mcp-layer.md) to understand the protocol architecture
3. **Learn Model Management**: Read [ML Models Documentation](docs/03-ml-models.md) to understand model upload and intelligence
4. **Review Managed Artefacts**: Inspect the model storage directory (`agent/model_storage/`) and its summary in [ML Models Documentation](docs/03-ml-models.md) to understand model organization
5. **Understand Features**: Review [Features Documentation](docs/04-features.md) to see what the agent can do
6. **Review Logic**: Study [Logic & Reasoning Documentation](docs/05-logic-reasoning.md) to understand how decisions are made
7. **Setup Development**: Follow [Deployment Documentation](docs/10-deployment.md) for environment setup, including the new consolidated `.env` guidance
8. **Follow Standards**: Adhere to [Project Rules](docs/14-project-rules.md) when contributing

**Building the Project**: The [Build Guide](docs/11-build-guide.md) contains executable commands that will build the entire project when followed sequentially. Use the `start` command (documented in the Build Guide) to launch JackSparrow locally after setup.

### Startup System Overview

The JackSparrow startup system provides comprehensive validation and monitoring:

#### Advanced Startup Features
- **4-Step Startup Sequence**: Environment loading → Paper trading validation → Configuration validation → Parallel service startup
- **Paper Trading Safety**: Built-in validation prevents accidental live trading execution
- **Configuration Validation**: Automatic environment variable and prerequisite checking
- **Health Checks**: Post-startup HTTP verification of all services
- **Real-time Monitoring**: Live dashboard with service status and data freshness tracking
- **WebSocket Monitoring**: Automatic connection monitoring and message freshness analysis

#### Key Startup Components
- `start_parallel.py`: Parallel process manager with comprehensive validation
- `PaperTradingValidator`: Safety mechanism preventing live trading accidents
- `MonitoringDashboard`: Real-time service monitoring and data freshness tracking
- `WebSocketMonitor`: WebSocket connection and message freshness monitoring
- `ValidationReporter`: Comprehensive validation reporting and recommendations

See [Architecture Documentation – Startup and Operations](docs/01-architecture.md#startup-and-operations) for detailed startup system architecture.

---

## 🔧 Command Reference

| Command | Purpose | Detailed Documentation |
| ------- | ------- | ---------------------- |
| `start` | Launch all JackSparrow services with comprehensive validation and monitoring | [Build Guide – Project Commands](docs/11-build-guide.md#project-commands) |
| `restart` | Stop any running services and relaunch the full stack from a clean slate | [Deployment Documentation – Operations](docs/10-deployment.md#project-commands) |
| `validate-prerequisites` | Validate system prerequisites before starting services | [Deployment Documentation – Startup Validation](docs/10-deployment.md#startup-validation-system) |
| `health_check` | Perform health checks on running services | [Deployment Documentation – Health Checks](docs/10-deployment.md#health-checks) |
| `validate-health` | Enhanced health validation with detailed reporting | [Deployment Documentation – Health Checks](docs/10-deployment.md#health-checks) |
| `start_and_test` | Start services and run continuous functionality tests | [File Structure – Command Toolkit](docs/08-file-structure.md#command-toolkit) |
| `audit` | Run a comprehensive system audit (code checks, service health, log review) | [Audit Report](docs/15-audit-report.md) |
| `error` | Inspect running services and log files for warnings or errors | [Backend Documentation – Operations](docs/06-backend.md#command-operations) |

---

## 📖 Documentation Structure Map

```
Trading Agent Documentation
│
├── DOCUMENTATION.md (this file — index only)
├── README.md
│
├── docs/
│   ├── 01-architecture.md … 15-audit-report.md   # Numbered canonical guides
│   ├── major-changes.md
│   ├── model-integration-summary.md
│   ├── project-comprehensive-documentation.md   # Long-form archive
│   ├── colab-quick-start.md
│   ├── docker-hot-reload*.md, training-and-feature-parity.md, …
│   ├── reports/            # Deep-dive / historical reports
│   ├── cursor/             # Cursor IDE setup notes
│   ├── analysis/           # Targeted analyses
│   └── archive/            # Timestamped snapshots
│
├── agent/model_storage/   # Trained bundles (see docs/03-ml-models.md, docs/model-integration-summary.md)
│
├── .env.example             # Environment template (see docs/10-deployment.md)
├── .env                     # Local runtime (gitignored)
│
└── reference/               # Design specs (rebuild, reasoning, implementation guides)
```

---

## 🔗 Cross-References

### By Topic

**Architecture & Design**
- [Architecture Documentation](docs/01-architecture.md) - System design
- [MCP Layer Documentation](docs/02-mcp-layer.md) - MCP architecture and protocols
- [File Structure Documentation](docs/08-file-structure.md) - Code organization

**Features & Functionality**
- [Features Documentation](docs/04-features.md) - What the agent does
- [Logic & Reasoning Documentation](docs/05-logic-reasoning.md) - How it thinks
- [ML Models Documentation](docs/03-ml-models.md) - Model management and intelligence

**Implementation**
- [Backend Documentation](docs/06-backend.md) - API and services
- [Frontend Documentation](docs/07-frontend.md) - User interface
- [UI/UX Documentation](docs/09-ui-ux.md) - Design guidelines

**Operations**
- [Build Guide](docs/11-build-guide.md) - Complete build instructions
- [Deployment Documentation](docs/10-deployment.md) - Setup and deployment
- [Docker Hot Reload Guide](docs/docker-hot-reload.md) - Hot reload setup and usage
- [Logging Documentation](docs/12-logging.md) - Centralized logging strategy
- [Project Rules Documentation](docs/14-project-rules.md) - Development standards

**Startup & Operations**
- [Architecture – Startup and Operations](docs/01-architecture.md#startup-and-operations) - Startup sequence and operational safety
- [Deployment – Startup Validation](docs/10-deployment.md#startup-validation-system) - Configuration and prerequisite validation
- [Deployment – Health Checks](docs/10-deployment.md#health-checks) - Service health verification
- [Deployment – Monitoring Dashboard](docs/10-deployment.md#monitoring-dashboard) - Real-time system monitoring
- [File Structure – Command Toolkit](docs/08-file-structure.md#command-toolkit) - Complete command reference

---

## 📝 Documentation Standards

All documentation files follow these standards:
- **Markdown format** with clear headings and structure
- **Code examples** included where relevant
- **Cross-references** to related documentation
- **Comprehensive coverage** of the topic
- **Consistent formatting** and style

---

## 🤝 Contributing

When adding or updating documentation:
1. Follow the structure and format of existing documentation
2. Update this index file if adding new documentation
3. Add cross-references to related documents
4. Ensure code examples are accurate and tested
5. Review [Project Rules](docs/14-project-rules.md) for documentation standards

---

## 📅 Last Updated

Documentation last updated: 2026-03-22

For the latest specifications and implementation details, refer to the files in the `reference/` directory.

### Recent Changes

- **[Major Changes Summary](docs/major-changes.md)** - Complete change log for architectural improvements (2025-01-27)
- **[Model Integration Summary](docs/model-integration-summary.md)** - v5 BTCUSD entry/exit ensembles, `MODEL_DIR`, and Docker bundle defaults
- **Documentation layout** - Root markdown reports moved under `docs/`, `docs/reports/`, and `docs/cursor/` (2026-03-22)
- **Startup System Documentation** - Comprehensive documentation of the advanced startup system including validation, health checks, and monitoring (2025-01-30)
- **Paper Trading Safety Features** - Documentation of safety mechanisms preventing accidental live trading
- **Real-time Monitoring Dashboard** - Documentation of the monitoring system with data freshness tracking
- **Command Toolkit Updates** - Expanded command reference with validation and health check tools

---

## 🆘 Need Help?

- **Building the project**: See [Build Guide](docs/11-build-guide.md) for step-by-step instructions
- **Architecture questions**: See [Architecture Documentation](docs/01-architecture.md)
- **MCP layer questions**: See [MCP Layer Documentation](docs/02-mcp-layer.md)
- **Model management**: See [ML Models Documentation](docs/03-ml-models.md)
- **Feature questions**: See [Features Documentation](docs/04-features.md)
- **Logging and observability**: See [Logging Documentation](docs/12-logging.md)
- **Implementation questions**: See [Backend](docs/06-backend.md) or [Frontend](docs/07-frontend.md) documentation
- **Setup issues**: See [Deployment Documentation](docs/10-deployment.md)
- **Docker hot reload**: See [Docker Hot Reload Guide](docs/docker-hot-reload.md)
- **Code standards**: See [Project Rules](docs/14-project-rules.md)

