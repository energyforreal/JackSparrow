# File Structure Documentation

## Overview

This document describes the complete project directory structure, file organization principles, and module responsibilities for the **JackSparrow** project.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Complete Project Structure](#complete-project-structure)
- [File Organization Principles](#file-organization-principles)
- [Module Responsibilities](#module-responsibilities)
- [Code Organization Patterns](#code-organization-patterns)
- [Configuration Files](#configuration-files)
- [Test Organization](#test-organization)
- [Scripts Organization](#scripts-organization)
- [Command Toolkit](#command-toolkit)
- [Documentation Organization](#documentation-organization)
- [Dependency Management](#dependency-management)
- [ML Model Storage](#ml-model-storage)
- [Related Documentation](#related-documentation)

---

## Complete Project Structure

```
JackSparrow/
├── backend/                             # Backend API service
│   ├── api/
│   │   ├── main.py                     # FastAPI application entry point
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── health.py               # Health check endpoints
│   │   │   ├── trading.py              # Trading operations endpoints
│   │   │   ├── portfolio.py            # Portfolio management endpoints
│   │   │   ├── market.py               # Market data endpoints
│   │   │   └── admin.py                # Admin/control endpoints
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py                 # Authentication middleware
│   │   │   ├── rate_limit.py           # Rate limiting middleware
│   │   │   ├── cors.py                 # CORS configuration
│   │   │   └── logging.py              # Request logging middleware
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── requests.py             # Pydantic request models
│   │   │   └── responses.py            # Pydantic response models
│   │   └── websocket/
│   │       ├── __init__.py
│   │       └── manager.py              # WebSocket connection manager
│   ├── services/
│   │   ├── __init__.py
│   │   ├── agent_service.py            # Agent communication service
│   │   ├── market_service.py           # Market data service
│   │   ├── portfolio_service.py       # Portfolio calculations service
│   │   └── feature_service.py         # MCP Feature Server client
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                   # Configuration management
│   │   ├── database.py                 # Database connection and models
│   │   └── redis.py                    # Redis connection
│   └── requirements.txt                # Python dependencies
│
├── agent/                               # AI Agent core
│   ├── core/
│   │   ├── __init__.py
│   │   ├── intelligent_agent.py       # Main agent class
│   │   ├── reasoning_engine.py        # MCP Reasoning Engine
│   │   ├── mcp_orchestrator.py         # MCP Orchestrator
│   │   ├── learning_system.py          # Learning module
│   │   ├── state_machine.py            # Agent state machine (see [Logic & Reasoning Documentation](05-logic-reasoning.md#enhanced-agent-state-machine))
│   │   └── context_manager.py         # Context management
│   ├── models/
│   │   ├── __init__.py
│   │   ├── mcp_model_node.py          # Base MCP model node interface
│   │   ├── mcp_model_registry.py      # MCP Model Registry
│   │   ├── model_discovery.py          # Automatic model discovery
│   │   ├── xgboost_node.py            # XGBoost implementation
│   │   ├── lstm_node.py               # LSTM implementation
│   │   ├── transformer_node.py        # Transformer implementation
│   │   ├── lightgbm_node.py           # LightGBM implementation
│   │   └── random_forest_node.py      # Random Forest implementation
│   ├── model_storage/                  # ML model storage directory
│   │   ├── custom/                     # User-uploaded models
│   │   │   ├── *.pkl                   # Pickle model files
│   │   │   ├── *.h5                    # TensorFlow/Keras models
│   │   │   ├── *.onnx                  # ONNX models
│   │   │   └── metadata.json           # Model metadata
│   │   ├── xgboost/                    # XGBoost models
│   │   │   ├── xgboost_v*.pkl
│   │   │   └── metadata.json
│   │   ├── lstm/                       # LSTM models
│   │   │   ├── lstm_v*.h5
│   │   │   └── metadata.json
│   │   └── transformer/               # Transformer models
│   │       ├── transformer_v*.onnx
│   │       └── metadata.json
│   ├── data/
│   │   ├── __init__.py
│   │   ├── feature_server.py          # MCP Feature Server
│   │   ├── feature_engineering.py     # Feature computation
│   │   ├── delta_client.py            # Delta Exchange client
│   │   └── market_data_service.py     # Market data ingestion
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_manager.py            # Risk management
│   │   └── position_sizer.py          # Position sizing logic
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── vector_store.py            # Vector memory store
│   │   └── embedding_service.py       # Embedding generation
│   ├── learning/
│   │   ├── __init__.py
│   │   ├── performance_tracker.py     # Performance tracking
│   │   ├── model_weight_adjuster.py   # Model weight updates
│   │   ├── confidence_calibrator.py   # Confidence calibration
│   │   └── strategy_adapter.py       # Strategy adaptation
│   └── requirements.txt               # Python dependencies
│
├── frontend/                            # Frontend web application
│   ├── app/
│   │   ├── layout.tsx                 # Root layout
│   │   ├── page.tsx                   # Main dashboard page
│   │   ├── components/
│   │   │   ├── Dashboard.tsx          # Main dashboard container
│   │   │   ├── AgentStatus.tsx         # Agent state indicator
│   │   │   ├── PortfolioSummary.tsx   # Portfolio overview
│   │   │   ├── ActivePositions.tsx     # Active positions list
│   │   │   ├── RecentTrades.tsx       # Recent trades list
│   │   │   ├── SignalIndicator.tsx    # Current signal display
│   │   │   ├── PerformanceChart.tsx   # Performance visualization
│   │   │   ├── HealthMonitor.tsx       # Health status display
│   │   │   ├── ReasoningChainView.tsx # Reasoning chain viewer
│   │   │   └── LearningReport.tsx     # Learning updates display
│   │   └── api/                       # API routes (if needed)
│   ├── hooks/
│   │   ├── useWebSocket.ts            # WebSocket hook
│   │   ├── useAgent.ts                # Agent state hook
│   │   ├── usePortfolio.ts            # Portfolio data hook
│   │   └── usePredictions.ts          # Prediction data hook
│   ├── services/
│   │   ├── api.ts                     # API client
│   │   └── websocket.ts               # WebSocket client
│   ├── types/
│   │   └── index.ts                   # TypeScript type definitions
│   ├── utils/
│   │   ├── formatters.ts              # Data formatting utilities
│   │   └── calculations.ts            # Calculation utilities
│   ├── styles/
│   │   └── globals.css                # Global styles
│   ├── package.json                   # Node.js dependencies
│   ├── tsconfig.json                  # TypeScript configuration
│   ├── next.config.js                 # Next.js configuration
│   └── tailwind.config.js             # Tailwind CSS configuration
│
├── tests/                              # Test suite
│   ├── unit/
│   │   ├── backend/
│   │   │   ├── test_services.py
│   │   │   └── test_routes.py
│   │   ├── agent/
│   │   │   ├── test_reasoning_engine.py
│   │   │   ├── test_models.py
│   │   │   └── test_learning.py
│   │   └── frontend/
│   │       └── test_components.test.tsx
│   ├── integration/
│   │   ├── test_backend_agent.py      # Backend-Agent integration
│   │   ├── test_frontend_backend.py   # Frontend-Backend integration
│   │   └── test_full_stack.py         # End-to-end tests
│   └── e2e/
│       └── test_dashboard_flows.py     # E2E dashboard tests
│
├── scripts/                            # Utility scripts
│   ├── setup_db.py                    # Database setup script
│   ├── train_models.py               # Model training script
│   ├── seed_data.py                  # Seed test data
│   ├── deploy.sh                      # Deployment script
│   └── migrate_db.py                 # Database migration script
│
├── tools/                             # Command toolkit
│   ├── commands/
│   │   ├── start_parallel.py          # Parallel process manager (Python, cross-platform)
│   │   ├── start.sh                   # Start stack wrapper (macOS/Linux)
│   │   ├── start.ps1                  # Start stack wrapper (Windows)
│   │   ├── restart.sh                 # Clean restart script
│   │   ├── restart.ps1                # Clean restart script (Windows)
│   │   ├── audit.sh                   # Audit automation
│   │   ├── audit.ps1                  # Audit automation (Windows)
│   │   ├── error.sh                   # Error diagnostics
│   │   └── error.ps1                  # Error diagnostics (Windows)
│   └── README.md                      # Toolkit usage notes
│
├── docs/                               # Documentation
│   ├── 01-architecture.md             # Architecture documentation
│   ├── 02-mcp-layer.md                # MCP layer documentation
│   ├── 03-ml-models.md                # ML models documentation
│   ├── 04-features.md                 # Features documentation
│   ├── 05-logic-reasoning.md          # Logic & reasoning documentation
│   ├── 06-backend.md                  # Backend documentation
│   ├── 07-frontend.md                 # Frontend documentation
│   ├── 08-file-structure.md           # This file
│   ├── 09-ui-ux.md                    # UI/UX documentation
│   ├── 10-deployment.md               # Deployment documentation
│   ├── 11-build-guide.md              # Build guide
│   ├── 12-logging.md                  # Logging documentation
│   ├── 13-debugging.md                # Debugging guide
│   ├── 14-project-rules.md            # Project rules documentation
│   └── 15-audit-report.md             # Audit report
│
├── models/                             # Production-ready ML artefacts (root level)
│   ├── *.pkl                           # Trained model binaries (versioned production models)
│   └── training_summary.csv            # Latest training metrics snapshot
│   # Note: Use MODEL_PATH env var to specify which model file to load
│
├── reference/                          # Reference specifications
│   ├── tradingagent_rebuild_spec.md
│   ├── trading_agent_rework.md
│   ├── agent_reasoning_spec.md
│   ├── implementation_guide.md
│   └── improvements_summary.md
│
├── tools/commands/                      # Command scripts (start, restart, audit, error)
├── logs/                                # Aggregated outputs from start/restart/audit/error
├── .env                                 # Runtime configuration (ignored from version control)
├── .env.example                       # Environment variables template
├── .gitignore                         # Git ignore rules
├── README.md                          # Project README
├── DOCUMENTATION.md                   # Documentation index
└── LICENSE                            # License file
```

---

## File Organization Principles

### Separation of Concerns

Each directory has a clear, single responsibility:

- **backend/**: API and service layer
- **agent/**: AI agent core logic
- **frontend/**: User interface
- **tests/**: Test code organized by type
- **scripts/**: Utility and setup scripts
- **docs/**: Documentation files
- **models/**: Versioned ML artefacts referenced by runtime configuration

### Module Boundaries

**Backend Module**:
- Handles HTTP requests/responses
- Manages WebSocket connections
- Provides API endpoints
- Does NOT contain agent logic

**Agent Module**:
- Contains AI reasoning logic
- Manages model inference via MCP Model Protocol
- Handles learning and adaptation
- Implements MCP layer (Feature, Model, Reasoning protocols)
- Manages ML model storage and discovery
- Does NOT handle HTTP directly

**Frontend Module**:
- User interface components
- API client code
- WebSocket client
- Does NOT contain business logic

**Example Mapping**:

| Concern        | Directory / File                                  | Notes                                                     |
|----------------|----------------------------------------------------|-----------------------------------------------------------|
| REST endpoint  | `backend/api/routes/trading.py`                    | Thin controller validates payloads and delegates to service layer |
| Business logic | `backend/services/agent_service.py`                | Coordinates with MCP orchestrator and handles retries     |
| Core reasoning | `agent/core/reasoning_engine.py`                   | Encodes the six-step reasoning flow                       |
| UI rendering   | `frontend/app/components/ReasoningChainView.tsx`   | Visualises reasoning chains received over WebSocket       |

When creating new functionality, choose the row that matches the responsibility; if a file starts to span multiple rows, split it before merging.

---

## Module Responsibilities

### Backend Module (`backend/`)

**Purpose**: Provide REST API and WebSocket interface for the trading agent.

**Key Responsibilities**:
- Handle HTTP requests
- Manage WebSocket connections
- Validate requests
- Format responses
- Error handling
- Authentication/authorization
- Rate limiting

**Dependencies**:
- Agent service (via message queue)
- Database (PostgreSQL)
- Redis (caching)
- Delta Exchange API

**Does NOT**:
- Contain agent reasoning logic
- Make trading decisions
- Train models

---

### Agent Module (`agent/`)

**Purpose**: Core AI agent with reasoning, decision-making, and learning capabilities.

**Key Responsibilities**:
- Market analysis
- Feature computation
- Model inference
- Reasoning chain generation
- Decision making
- Risk management
- Learning and adaptation

**Dependencies**:
- MCP Orchestrator (coordinates all MCP components)
- Feature Server (MCP Feature Protocol)
- Model Registry (MCP Model Protocol)
- Model Storage (`agent/model_storage/` directory)
- Vector database (memory)
- Database (storage)
- Delta Exchange API (execution)

**Does NOT**:
- Handle HTTP requests directly
- Manage WebSocket connections
- Format API responses

---

### Frontend Module (`frontend/`)

**Purpose**: User interface for monitoring and interacting with the trading agent.

**Key Responsibilities**:
- Display agent status
- Show portfolio information
- Visualize performance
- Display reasoning chains
- Handle user interactions
- Real-time updates via WebSocket

**Dependencies**:
- Backend API
- WebSocket connection

**Does NOT**:
- Contain business logic
- Make trading decisions
- Access database directly

---

## Code Organization Patterns

### Python Code Organization

**Package Structure**:
```
module/
├── __init__.py          # Package initialization
├── core.py              # Core functionality
├── utils.py             # Utility functions
└── exceptions.py        # Custom exceptions
```

**Naming Conventions**:
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions: `snake_case()`
- Constants: `UPPER_SNAKE_CASE`

**Import Organization**:
```python
# Standard library imports
import os
import sys
from datetime import datetime

# Third-party imports
import fastapi
import numpy as np

# Local imports
from .core import Agent
from .utils import format_price
```

---

### TypeScript/React Code Organization

**Component Structure**:
```typescript
// Component file
import React from 'react';
import { ComponentProps } from './types';

export function ComponentName({ prop1, prop2 }: ComponentProps) {
  // Component logic
  return <div>...</div>;
}

// Types file
export interface ComponentProps {
  prop1: string;
  prop2: number;
}
```

**File Naming**:
- Components: `PascalCase.tsx`
- Hooks: `useCamelCase.ts`
- Utilities: `camelCase.ts`
- Types: `types.ts` or `index.ts`

**Import Organization**:
```typescript
// React imports
import React, { useState, useEffect } from 'react';

// Third-party imports
import { format } from 'date-fns';

// Local imports
import { useWebSocket } from '@/hooks/useWebSocket';
import { apiClient } from '@/services/api';
```

---

## Configuration Files

### Backend Configuration

**`backend/core/config.py`**:
- Environment variable loading
- Configuration validation
- Default values
- Configuration classes

**Environment Variables**:
- Database connection strings
- API keys
- Service URLs
- Feature flags

---

### Frontend Configuration

**`frontend/next.config.js`**:
- Next.js configuration
- Environment variables
- Build settings
- API routes

**`frontend/tailwind.config.js`**:
- Tailwind CSS configuration
- Color palette
- Spacing scale
- Custom utilities

**`frontend/tsconfig.json`**:
- TypeScript configuration
- Path aliases
- Compiler options
- Type checking rules

---

## Test Organization

### Unit Tests

**Location**: `tests/unit/`

**Structure**:
- Mirror source structure
- One test file per source file
- Test file naming: `test_*.py` or `*.test.tsx`

**Example**:
```
backend/services/agent_service.py
tests/unit/backend/test_agent_service.py
```

---

### Integration Tests

**Location**: `tests/integration/`

**Purpose**: Test interactions between modules

**Examples**:
- Backend-Agent communication
- Frontend-Backend API calls
- Database operations
- WebSocket communication

---

### End-to-End Tests

**Location**: `tests/e2e/`

**Purpose**: Test complete user flows

**Examples**:
- Dashboard loading
- Trade execution flow
- Real-time updates
- Error handling

---

## Scripts Organization

### Setup Scripts

**`scripts/setup_db.py`**:
- Database initialization
- Table creation
- Index creation
- Initial data seeding

**`scripts/train_models.py`**:
- Model training
- Hyperparameter tuning
- Model evaluation
- Model saving

---

### Utility Scripts

**`scripts/seed_data.py`**:
- Test data generation
- Historical data import
- Mock data creation

**`scripts/migrate_enums.py`**:
- Database schema migration for ENUM types
- Converts VARCHAR enum columns to PostgreSQL ENUM types
- Required for existing databases created before ENUM support
- Includes transaction safety and rollback capability

---

### Deployment Scripts

**`scripts/deploy.sh`**:
- Deployment automation
- Environment setup
- Service restart
- Health checks

---

### Command Automation

**Command Scripts (tools/commands/)**:
- `start_parallel.py`: Launches backend, agent, and frontend services simultaneously using parallel process manager; streams real-time logs to console and writes to `logs/{service}.log`. Automatically validates configuration and prerequisites before starting.
- `start.sh` / `start.ps1`: Shell script wrappers for `start_parallel.py` (Linux/macOS and Windows respectively).
- `restart.sh` / `restart.ps1`: Stops running services, clears temporary artefacts, re-executes start command, and archives previous logs under `logs/restart/`.
- `audit.sh` / `audit.ps1`: Runs formatting, linting, tests, health checks, and log aggregation; produces reports in `logs/audit/`.
- `error.sh` / `error.ps1`: Performs a lightweight diagnostic (process status + log tail) and stores results in `logs/error/summary.log`.
- `validate-prerequisites.py`: Validates system prerequisites (Python, Node.js, PostgreSQL, Redis).
- `health_check.py`: Checks health of running services.

Supporting helper scripts live under `scripts/` and are invoked automatically by the command scripts.

---

## Command Toolkit

### Location
- Directory: `tools/commands/`
- Companion docs: `tools/README.md`

### Available Commands
- `start_parallel.py`: Python-based parallel process manager (cross-platform) - starts all services simultaneously
- `start.sh` / `start.ps1`: Wrapper scripts that invoke `start_parallel.py` for convenience
- `restart.sh` / `restart.ps1`: Perform a clean shutdown and restart
- `audit.sh` / `audit.ps1`: Run formatting, tests, health checks, and log review
- `error.sh` / `error.ps1`: Gather live diagnostics and recent log summaries

### Invocation Options
- Direct Python execution (`python tools/commands/start_parallel.py`) - recommended for fastest startup
- Direct script execution (`./tools/commands/start.sh` or `start.ps1`)
- Command scripts (`tools/commands/start_parallel.py`, `tools/commands/audit.sh`, etc.)
- PowerShell scripts for Windows environments

### Log Outputs
- All commands write to the `logs/` tree:
  - `logs/backend.log` - Backend service logs
  - `logs/agent.log` - Agent service logs
  - `logs/frontend.log` - Frontend service logs
  - `logs/backend.pid`, `logs/agent.pid`, `logs/frontend.pid` - Process ID files
  - `logs/restart.log` - Restart operation logs
  - `logs/audit/` - Audit reports
  - `logs/error/`

---

## Documentation Organization

### Documentation Files

**Location**: `docs/`

**Structure**:
- One file per major topic
- Cross-references between documents
- Consistent formatting
- Code examples included

**Files**:
- `01-architecture.md`: System design
- `02-mcp-layer.md`: MCP layer architecture
- `03-ml-models.md`: ML model management
- `04-features.md`: Feature specifications
- `05-logic-reasoning.md`: AI reasoning docs
- `06-backend.md`: Backend API docs
- `07-frontend.md`: Frontend docs
- `08-file-structure.md`: This file
- `09-ui-ux.md`: Design guidelines
- `10-deployment.md`: Setup instructions
- `11-build-guide.md`: Build instructions
- `12-logging.md`: Logging documentation
- `13-debugging.md`: Debugging guide
- `14-project-rules.md`: Development standards
- `15-audit-report.md`: Audit report

---

## Dependency Management

### Python Dependencies

**Backend**: `backend/requirements.txt`
**Agent**: `agent/requirements.txt`

**Organization**:
```txt
# Core dependencies
fastapi==0.104.0
uvicorn==0.24.0

# Database
sqlalchemy==2.0.23
psycopg2-binary==2.9.9

# ML/AI
xgboost==2.0.2
tensorflow==2.14.0

# Utilities
python-dotenv==1.0.0
pydantic==2.5.0
```

---

### Node.js Dependencies

**Frontend**: `frontend/package.json`

**Organization**:
```json
{
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.0.0",
    "typescript": "^5.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.0.0",
    "tailwindcss": "^3.0.0"
  }
}
```

---

## ML Model Storage

### Model Storage Locations

JackSparrow uses two distinct model storage locations:

1. **Root `models/` directory** - Production models shipped with codebase
   - Contains versioned production model files (`.pkl` files)
   - Referenced via `MODEL_PATH` environment variable (points to specific file)
   - Example: `MODEL_PATH=models/xgboost_BTCUSD_15m.pkl`
   - Used at runtime to load a specific production model

2. **`agent/model_storage/` directory** - Upload directory for new/custom models
   - Contains uploaded models that are discovered automatically
   - Referenced via `MODEL_DIR` environment variable (points to directory)
   - Example: `MODEL_DIR=./agent/model_storage`
   - Used by model discovery system to find and register models

### Model Directory Structure

**Production Models** (`models/` at root):
```
models/
├── xgboost_BTCUSD_15m.pkl              # Production model files
├── xgboost_BTCUSD_1h.pkl
├── lightgbm_BTCUSD_4h_production_*.pkl
└── training_summary.csv                 # Training metrics
```

**Upload Directory** (`agent/model_storage/`):
```
agent/model_storage/
├── custom/              # User-uploaded models (discovered automatically)
│   ├── *.pkl           # Pickle models (XGBoost, LightGBM, scikit-learn)
│   ├── *.h5            # TensorFlow/Keras models
│   ├── *.onnx          # ONNX models
│   └── metadata.json   # Model metadata
├── xgboost/            # XGBoost models (uploaded)
├── lstm/               # LSTM models (uploaded)
└── transformer/        # Transformer models (uploaded)
```

### Model Discovery

Models in `agent/model_storage/` are automatically discovered on agent startup:
- Scans directories specified by `MODEL_DIR`
- Detects model type from file extension and metadata
- Registers models with MCP Model Registry
- Models become available for predictions immediately

**Production models** in `models/` are loaded directly via `MODEL_PATH` and do not require discovery.

For detailed model management documentation, see [ML Models Documentation](03-ml-models.md).

---

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - MCP architecture and protocols
- [ML Models Documentation](03-ml-models.md) - Model management and intelligence
- [Architecture Documentation](01-architecture.md) - System design
- [Backend Documentation](06-backend.md) - Backend implementation
- [Frontend Documentation](07-frontend.md) - Frontend implementation
- [Project Rules](14-project-rules.md) - Coding standards
- [Build Guide](11-build-guide.md) - Build instructions

