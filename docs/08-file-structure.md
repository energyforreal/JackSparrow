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
│   │   │   ├── admin.py                # Admin/control endpoints
│   │   │   └── system.py               # System/time synchronization endpoints
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
│   │       ├── unified_manager.py      # Active WebSocket manager used by backend.api.main
│   │       └── manager.py              # Legacy manager retained for compatibility/testing
│   ├── services/
│   │   ├── __init__.py
│   │   ├── agent_service.py            # Agent communication service
│   │   ├── agent_event_subscriber.py   # Agent event ingestion + WS fanout
│   │   ├── health_poller.py            # Background health polling and cache updates
│   │   ├── market_service.py           # Market data service
│   │   ├── portfolio_service.py        # Portfolio calculations service
│   │   ├── trade_persistence_service.py # Trade + position persistence helpers
│   │   ├── feature_service.py          # MCP Feature Server client (currently not wired in runtime)
│   │   └── time_service.py             # Time normalization and formatting service
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
│   │   ├── execution.py                # Trade execution engine (now lot-based for futures)
│   │   ├── sl_tp.py                    # Shared stop/take-profit pricing (ATR + fixed %, tick rounding, paper rebase helper)
│   │   ├── audit_time.py               # IST/UTC helpers for paper + signal-audit logs
│   │   ├── paper_trade_logger.py       # Rotating `paper_trades.log` (TRADE|/CLOSE|)
│   │   ├── signal_audit_md.py          # Append-only `live_audit.md` (ai_signal, gates, paper echo)
│   │   ├── config.py                   # Agent configuration includes perpetual futures parameters
│   ├── data/
│   │   ├── perpetual_data_fetcher.py   # Perpetual futures candles/orderbook loader and normalizer
│   │   ├── ...

├── feature_store/                      # Per-feature engineering layer
│   ├── feature_registry.py            # Canonical and perpetual feature lists
│   ├── unified_feature_engine.py      # Batch/single feature computation including perpetual markets
│   ├── jacksparrow_v43_contract.py   # v43 training contract: `V43_CANONICAL_FEATURES`, horizon constant
│   ├── jacksparrow_v43_build_matrix.py  # `build_v43_feature_matrix` (training + shim transform)
│   ├── jacksparrow_v43_mcp_row.py     # Ordered MCP feature row builder for v43 inference
│   ├── perpetual_features.py          # Perpetual-specific feature computation
│   └── ...
│   │   ├── mcp_orchestrator.py         # MCP Orchestrator (NEW - complete implementation)
│   │   ├── learning_system.py          # Learning module (TODO - needs implementation)
│   │   ├── state_machine.py            # Agent state machine (see [Logic & Reasoning Documentation](05-logic-reasoning.md#enhanced-agent-state-machine))
│   │   ├── context_manager.py         # Context management (TODO - needs implementation)
│   │   └── execution.py                # Trade execution engine (TODO - needs implementation)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── websocket_server.py         # Backend→agent command WebSocket bridge (active)
│   │   ├── websocket_client.py         # Agent→backend event WebSocket client (active)
│   │   └── feature_server.py           # Legacy standalone FastAPI bridge (compat/diagnostics)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── mcp_model_node.py          # Base MCP model node interface
│   │   ├── mcp_model_registry.py      # MCP Model Registry
│   │   ├── model_discovery.py          # JackSparrow v43 bundle discovery (metadata_v43.json)
│   │   ├── jack_sparrow_v43_node.py   # v43 MCP model node (+ inference + pickle shims used at load time)
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
│   │   ├── feature_server_api.py      # Active aiohttp bridge used by IntelligentAgent
│   │   ├── feature_engineering.py     # Feature computation
│   │   ├── candle_store.py            # Parquet storage for closed OHLCV candles
│   │   ├── delta_client.py            # Delta Exchange client
│   │   └── market_data_service.py     # Market data ingestion
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_manager.py            # Risk management
│   │   └── position_sizer.py          # Legacy standalone helper (runtime uses RiskManager.calculate_position_size)
│   ├── scripts/
│   │   ├── __init__.py
│   │   └── dev_watcher.py             # Docker-dev hot-reload watcher for `agent.core.intelligent_agent`
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── vector_store.py            # Vector memory store
│   │   └── embedding_service.py       # Embedding generation
│   ├── learning/
│   │   ├── __init__.py
│   │   ├── performance_tracker.py     # Directional accuracy/PnL tracker (bounded history)
│   │   ├── model_weight_adjuster.py   # Adaptive model weights (accuracy + saturated profit)
│   │   ├── confidence_calibrator.py   # Confidence calibration with cold-start safeguards
│   │   ├── strategy_adapter.py        # Parameter adaptation from aggregate evaluated outcomes
│   │   ├── dynamic_thresholds.py      # Redis threshold overrides with bounded clamps
│   │   ├── threshold_adapter.py       # Periodic threshold nudging from recent trade_outcomes
│   │   ├── retraining_scheduler.py    # Trigger + execute retraining command with cooldown/state
│   │   └── adaptive/                  # Optional v15: KS drift, warm-start XGBoost, F1 gate, versioned saves
│   │       ├── adaptive_controller.py # Orchestration + hot reload hook
│   │       ├── drift_detector.py
│   │       ├── retrain_engine.py
│   │       ├── model_validator.py
│   │       ├── model_registry.py
│   │       └── labeled_data.py        # Parquet loader for labeled_{tf}.parquet
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
│   │   ├── formatters.ts              # Data formatting utilities (currency, percentages, timestamps)
│   │   │                              # Includes UTC→IST time conversion and normalization
│   │   ├── portfolioMetrics.ts        # ROE: unrealized PnL ÷ margin (PortfolioSummary badge)
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
├── scripts/                            # Utility scripts (training, audits, DB, etc.)
│   ├── dev/                           # Ad-hoc dev helpers (startup logging, direct_run)
│   ├── notebooks/                    # One-off notebook maintenance (cell dump, restore)
│   ├── ml_system.py                 # Shared ML helpers (used by train_robust_ensemble)
│   ├── train_exit_models.py         # Exit-model training (robust_ensemble layout)
│   ├── verify_exit_models.py        # Load-test saved exit models
│   ├── validate_copied_models.py    # Wrapper around validate_model_files for agent/model_storage
│   ├── setup_db.py                  # Database setup script
│   ├── train_models.py              # Model training script
│   └── …                            # Other training, audit, and migration scripts
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
- **tests/**: Test code organized by type, plus `tests/functionality/reports/` for **generated** test reports (not kept in version control)
- **scripts/**: Utility and setup scripts; `scripts/dev/` for local debugging helpers; `scripts/notebooks/` for rare notebook edits
- **docs/**: Canonical documentation only — `01-architecture.md` through `15-audit-report.md` (see [DOCUMENTATION.md](../DOCUMENTATION.md))

**Cleanup Guidance (2026-04-01 audit)**:
- `agent/risk/position_sizer.py` is currently not referenced by runtime code paths; keep only for compatibility or remove after confirming no external imports.
- `agent/venv/` should remain local-only and excluded from version control; do not place source code under this path.
- `agent/scripts/dev_watcher.py` is active in Docker development flow (`Dockerfile.dev`), so it should be retained.
- `backend/api/websocket/manager.py` is not used by `backend/api/main.py` runtime paths (which use `unified_manager.py`); treat it as legacy until removed.
- `backend/services/feature_service.py` is currently not imported by backend runtime code paths; remove or wire it explicitly.
- `notebooks/` holds **`jacksparrow_v43_delta_india_training.ipynb`** (v43 Delta India training, contract-aligned export). Legacy multi-notebook sets were removed; see `docs/03-ml-models.md` for archival bundle notes.

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

### Core Startup System

#### `start_parallel.py` - Parallel Process Manager

**Purpose**: Comprehensive startup system with validation, monitoring, and health checks.

**Key Features**:
- **4-Step Startup Sequence**: Environment loading → Paper trading validation → Redis check → Configuration validation → Service startup
- **Paper Trading Safety**: Validates `PAPER_TRADING_MODE` and `TRADING_MODE` to prevent accidental live trading
- **Configuration Validation**: Automatic environment variable and prerequisite validation
- **Health Checks**: Post-startup HTTP health verification for all services
- **Monitoring Dashboard**: Real-time service monitoring with data freshness tracking
- **WebSocket Monitoring**: Automatic connection monitoring and message freshness analysis
- **Validation Reporting**: Comprehensive validation reports with recommendations

**Capabilities**:
- Cross-platform (Windows, macOS, Linux)
- Parallel service startup (faster than sequential)
- Real-time log streaming with color coding
- Graceful shutdown handling
- Process lifecycle management

**Usage**:
```bash
python tools/commands/start_parallel.py
```

#### `start.sh` / `start.ps1` - Convenience Wrappers

**Purpose**: Shell script wrappers for `start_parallel.py`.

**Platforms**:
- `start.sh`: Linux/macOS
- `start.ps1`: Windows PowerShell

**Functionality**: Invoke `start_parallel.py` with appropriate shell integration.

### Validation Commands

#### `validate-prerequisites.py` - System Prerequisites

**Purpose**: Validate system requirements before starting services.

**Validates**:
- Python 3.11+ availability and version
- Node.js 18+ availability and version
- PostgreSQL connection and version
- Redis connection and version

**Usage**:
```bash
python tools/commands/validate-prerequisites.py
```

#### `validate-health.py` - Enhanced Health Validation

**Purpose**: Comprehensive health validation with detailed reporting.

**Features**:
- Detailed health status for all services
- Performance metrics and latency information
- Recommendations for failed services
- Troubleshooting guidance

**Usage**:
```bash
python tools/commands/validate-health.py
```

#### `health_check.py` - Basic Health Checks

**Purpose**: Quick health verification for running services.

**Checks**:
- Backend service health (`http://localhost:8000/api/v1/health`)
- Feature server health (`http://localhost:${FEATURE_SERVER_PORT:-8001}/health`)
- Frontend accessibility

**Usage**:
```bash
python tools/commands/health_check.py
```

### Testing and Monitoring

#### `start_and_test.py` - Orchestrated Testing

**Purpose**: Start services and run continuous functionality tests.

**Features**:
- Automated service startup
- Continuous test execution (configurable intervals)
- Parallel test execution modes
- Failure detection and termination
- Comprehensive test reporting

**Usage**:
```bash
python tools/commands/start_and_test.py
python tools/commands/start_and_test.py --test-interval 60
python tools/commands/start_and_test.py --groups infrastructure,core-services
```

### Management Commands

#### `restart.sh` / `restart.ps1` - Clean Restart

**Purpose**: Perform clean shutdown and restart of all services.

**Actions**:
1. Gracefully stop backend, agent, and frontend processes
2. Clear temporary artifacts (PID files, cached sockets)
3. Re-run the startup command

#### `audit.sh` / `audit.ps1` - System Audit

**Purpose**: Run comprehensive system audit.

**Checks**:
- Python code quality (ruff, black, pytest)
- Frontend quality (lint, test)
- Service health checks
- Log review for errors/warnings
- Report generation

#### `error.sh` / `error.ps1` - Diagnostics Collection

**Purpose**: Gather live diagnostics and recent log summaries.

**Collects**:
- Process status for all services
- Latest log lines per service
- Summary of new warnings/errors
- Diagnostic output with timestamps

### Invocation Options

**Recommended Methods**:
1. **Direct Python**: `python tools/commands/start_parallel.py` (fastest, most reliable)
2. **Shell Scripts**: `./tools/commands/start.sh` or `.\tools/commands\start.ps1`
3. **PowerShell**: For Windows environments with proper execution policy

### Log Outputs

**All commands write to the `logs/` directory**:

**Service Logs**:
- `logs/backend.log` - Backend service logs
- `logs/agent.log` - Agent service logs
- `logs/frontend.log` - Frontend service logs

**Process Management**:
- `logs/backend.pid`, `logs/agent.pid`, `logs/frontend.pid` - Process ID files

**Operation Logs**:
- `logs/start.log` - Startup sequence logs
- `logs/restart.log` - Restart operation logs
- `logs/audit/` - Audit reports and results
- `logs/error/` - Diagnostic collections

**Validation Reports**:
- `logs/validation/` - Configuration and prerequisite validation results

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

### Model Storage Location

JackSparrow ships trained ML artefacts under **`agent/model_storage/`**, referenced by **`MODEL_DIR`** (**`AGENT_MODEL_DIR`** in Docker). **Current discovery loads a single JackSparrow v43 bundle**: path must contain **`metadata_v43.json`**. The checked-in default bundle root is **`agent/model_storage/JackSparrow_v43_models_BTCUSD/`**; promote Colab exports (`metadata_v43.json`, `model_artifact_v43.pkl`) there unless you point **`MODEL_DIR`** at another folder. Older layouts with **`metadata_BTCUSD_*.json`** remain in the tree as **historical** exports; **`MODEL_FORMAT` defaults to `jacksparrow_v43`** (health/integration label—not a loader switch).

**Typical layouts**:

- **v43 regression (Compose default)**: **`JackSparrow_v43_models_BTCUSD/`** — flat folder: **`metadata_v43.json`** + **`model_artifact_v43*.pkl`** (+ optional `feature_engineer.pkl`, `regime_models_v43.pkl`) — **`JackSparrowV43Node`**.
- **Historical v5 / v4 ensemble** (entry + exit joblibs per timeframe), e.g. `jacksparrow_v5_BTCUSD_2026-03-19/` — **`V4EnsembleNode`** in forks only.
- **Historical v15 pipeline** (single `pipeline_{tf}_v14.pkl` per TF), e.g. `jacksparrow_v15_BTCUSD_2026-04-05/{5m,15m}/` — retained for parquet **adaptive retrain**, not paired with today's v43 **`ModelDiscovery`**.

Example v43 tree:

```
agent/model_storage/JackSparrow_v43_models_BTCUSD/
├── metadata_v43.json              # promotion metadata + validation_metrics
├── model_artifact_v43.pkl         # Colab export (base)
├── model_artifact_v43_patched.pkl # runtime default (patch script output)
├── model_artifact_v43_old_*.pkl   # local rollback copies (optional, not always in git)
├── metadata_v43_old_*.json
├── feature_engineer.pkl           # optional sidecar
└── regime_models_v43.pkl          # optional
```

Promote Colab exports with [`scripts/patch_v43_model_artifact.py`](../scripts/patch_v43_model_artifact.py); see [ML models — Operational Workflow](03-ml-models.md#operational-workflow-bundle-first).

Example legacy v5 tree:

```
agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19/
├── metadata_BTCUSD_15m.json
├── entry_model_BTCUSD_15m.joblib
├── exit_model_BTCUSD_15m.joblib
└── ...
```

Example v15 tree:

```
agent/model_storage/jacksparrow_v15_BTCUSD_2026-04-05/
├── 5m/metadata_BTCUSD_5m.json
├── 5m/pipeline_5m_v14.pkl
├── 15m/metadata_BTCUSD_15m.json
└── 15m/pipeline_15m_v14.pkl
```

### Model Discovery

- **`agent/models/model_discovery.py`** resolves **`MODEL_DIR/metadata_v43.json`** and registers **`JackSparrowV43Node`** (`MODEL_AUTO_REGISTER=true` by default). **`MODEL_PATH` is ignored.**
- Legacy recursive scans for **`metadata_BTCUSD_*.json`** apply only when running an older checkout or patched discovery—see **[ML Models](03-ml-models.md#historical-multi-node-flow-forks-only)**.

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

