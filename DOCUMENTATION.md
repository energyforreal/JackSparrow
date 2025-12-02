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
   - Currently integrated: 6 XGBoost models (3 classifiers + 3 regressors) for BTCUSD trading
   - **[ML Training Guide - Google Colab](docs/ml-training-google-colab.md)** - Comprehensive guide for training models in Google Colab
   - **[Model Integration Summary](MODEL_INTEGRATION_SUMMARY.md)** - Details on recent model integration

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
   - Component architecture
   - WebSocket integration
   - State management patterns
   - Real-time update mechanisms
   - UI component specifications

8. **[File Structure Documentation](docs/08-file-structure.md)**
   - Complete project directory structure
   - File organization principles
   - Module responsibilities
   - Code organization patterns
   - ML model storage structure

### Design & Deployment

9. **[UI/UX Documentation](docs/09-ui-ux.md)**
   - Dashboard design specifications
   - Component design guidelines
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
    - Docker deployment (alternative containerized deployment option)
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

13. **[Debugging & Error Handling Guide](docs/13-debugging.md)**
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
   - Related: [Docker Logs Follow-up Report](docs/archive/docker-logs-followup-report-2025-11-20.md), [Docker Logs Analysis Report - 2025-11-23](docs/archive/docker-logs-analysis-report-2025-11-23.md)

19. **[Remediation Plan](docs/remediation-plan.md)**
   - Step-by-step remediation for identified issues
   - Implementation priorities
   - Testing checklists
   - Rollback procedures

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

---

## 🔧 Command Reference

| Command | Purpose | Detailed Documentation |
| ------- | ------- | ---------------------- |
| `start` | Launch all JackSparrow services on the local workstation (backend, agent, frontend) | [Build Guide – Project Commands](docs/11-build-guide.md#project-commands) |
| `restart` | Stop any running services and relaunch the full stack from a clean slate | [Deployment Documentation – Operations](docs/10-deployment.md#project-commands) |
| `audit` | Run a comprehensive system audit (code checks, service health, log review) | [Audit Report](docs/15-audit-report.md) |
| `error` | Inspect running services and log files for warnings or errors | [Backend Documentation – Operations](docs/06-backend.md#command-operations) |

---

## 📖 Documentation Structure Map

```
Trading Agent Documentation
│
├── DOCUMENTATION.md (this file)
│
├── docs/
│   ├── architecture.md          # System architecture and design
│   ├── mcp-layer.md             # MCP layer architecture and orchestration
│   ├── ml-models.md             # ML model management and intelligence
│   ├── features.md              # Feature specifications
│   ├── logic-reasoning.md       # AI reasoning and decision-making
│   ├── backend.md               # Backend API and services
│   ├── frontend.md              # Frontend application
│   ├── file-structure.md        # Project organization
│   ├── ui-ux.md                 # User interface design
│   ├── deployment.md            # Setup and deployment
│   ├── docker-hot-reload.md     # Docker hot reload guide
│   ├── docker-hot-reload-quick-reference.md  # Quick command reference
│   ├── docker-hot-reload-implementation-summary.md  # Implementation details
│   ├── docker-hot-reload-testing-guide.md   # Testing procedures
│   ├── build-guide.md           # Complete build instructions
│   ├── logging.md               # Centralized logging plan
│   ├── project-rules.md         # Development standards
│   ├── 15-audit-report.md       # Documentation audit report
│   ├── audit-report-consolidated.md  # Consolidated audit report
│   ├── audit-summary-2025-01-27.md  # Audit summary
│   ├── comprehensive-audit-report.md  # Complete audit report
│   ├── docker-logs-analysis-report-current.md # Current Docker logs analysis
│   ├── docker-logs-agent-communication-analysis.md # Agent communication analysis
│   ├── remediation-plan.md      # Issue remediation plan
│   └── archive/
│       ├── docker-logs-followup-report-2025-11-20.md  # Docker logs follow-up (archived)
│       ├── docker-logs-analysis-report-2025-11-20.md  # Timestamped analysis (archived)
│       └── docker-logs-analysis-report-2025-11-23.md  # Timestamped analysis (archived)
│
├── models/                      # Managed production artefacts (see docs/03-ml-models.md)
│   ├── *.pkl                    # Trained model binaries
│   └── training_summary.csv     # Latest training metrics
│
├── .env.example                 # Environment variables template (see docs/10-deployment.md)
├── .env                         # Runtime configuration (ignored by VCS, copy from .env.example)
│
└── reference/                   # Reference specifications
    ├── tradingagent_rebuild_spec.md
    ├── trading_agent_rework.md
    ├── agent_reasoning_spec.md
    ├── implementation_guide.md
    └── improvements_summary.md
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

Documentation last updated: 2025-01-28

For the latest specifications and implementation details, refer to the files in the `reference/` directory.

### Recent Changes

- **[Major Changes Summary](MAJOR_CHANGES.md)** - Complete change log for architectural improvements (2025-01-27)
- **[Model Integration Summary](MODEL_INTEGRATION_SUMMARY.md)** - Details on integration of 6 XGBoost models for BTCUSD trading

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

