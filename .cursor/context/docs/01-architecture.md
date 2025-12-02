# Architecture Documentation

## System Architecture Overview

**JackSparrow** follows a **three-tier architecture** pattern, separating concerns into distinct layers:

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

## Table of Contents

- [System Architecture Overview](#system-architecture-overview)
- [Three-Tier Architecture](#three-tier-architecture)
  - [Layer 1: Data Layer](#layer-1-data-layer)
  - [Layer 2: Intelligence Layer (AI Agent Core)](#layer-2-intelligence-layer-ai-agent-core)
  - [Layer 3: Presentation Layer](#layer-3-presentation-layer)
- [MCP Protocol Integration](#mcp-protocol-integration)
- [Component Definitions](#component-definitions)
- [Integration Points](#integration-points)
- [Communication Protocols](#communication-protocols)
- [Error Handling Strategy](#error-handling-strategy)
- [Data Flow](#data-flow)
- [Scalability Considerations](#scalability-considerations)
- [Security Considerations](#security-considerations)
- [Related Documentation](#related-documentation)

1. **Data Layer** - Market data ingestion, feature computation, and storage
2. **Intelligence Layer** - AI agent core with reasoning and decision-making
3. **Presentation Layer** - User interfaces and API endpoints

---

## Three-Tier Architecture

### Layer 1: Data Layer

The Data Layer is responsible for:
- Real-time and historical market data ingestion from Delta Exchange
- Feature engineering and computation
- Data quality monitoring
- Time-series data storage

#### Components

**Market Data Service**
- Fetches real-time ticker data from Delta Exchange API
- Retrieves historical OHLCV data
- Implements circuit breakers for API failures
- Caches frequently accessed data

**Feature Store (MCP Feature Server)**
- Computes technical indicators and ML features
- Maintains feature versioning (semantic versioning)
- Monitors feature quality (HIGH, MEDIUM, LOW, DEGRADED)
- Provides standardized MCP Feature Protocol interface

**State Management**
- Portfolio state tracking
- Position management
- Trade history storage
- Performance metrics calculation

**Time-Series Database**
- TimescaleDB (PostgreSQL extension) for efficient time-series queries
- Optimized for OHLCV data storage
- Partitioned by time intervals
- Fast aggregation queries

### Layer 2: Intelligence Layer (AI Agent Core)

The Intelligence Layer contains the "brain" of the trading agent:

**Signal Generation Engine**
- Multi-model ML inference system
- Ensemble of models: XGBoost, LightGBM, LSTM, Transformer, Random Forest
- Parallel model execution
- Model health monitoring

**Decision Engine (MCP Reasoning Engine)**
- 6-step structured reasoning chain
- Multi-model consensus calculation
- Context-aware decision making
- Risk-adjusted position sizing

**Risk Manager**
- Circuit breakers for portfolio protection
- Position sizing based on Kelly Criterion
- Volatility-adjusted stop losses
- Portfolio heat monitoring

**Learning Module**
- Performance tracking per model
- Dynamic model weight adjustment
- Strategy parameter adaptation
- Confidence calibration

**Vector Memory Store**
- Stores decision contexts as embeddings
- Retrieves similar past situations
- Enables learning from historical patterns

### Layer 3: Presentation Layer

**FastAPI Backend**
- REST API endpoints
- WebSocket server for real-time updates
- Authentication and authorization
- Request logging and monitoring

**Next.js Frontend**
- Real-time dashboard
- Agent status visualization
- Portfolio and performance displays
- Reasoning chain viewer
- Learning reports

**Telegram Interface** (Optional - Future Enhancement)
- Mobile notifications for trades and alerts
- Command interface for manual controls
- Status updates and monitoring
- Not required for core functionality
- Can be implemented as separate optional service

**Monitoring Stack**
- Prometheus metrics collection
- Grafana dashboards
- Structured logging
- Error tracking

---

## MCP Protocol Integration

### What is MCP (Model Context Protocol)?

MCP is a standardized protocol for AI systems to:
- Maintain context across components
- Communicate with ML models consistently
- Share features and predictions with versioning
- Enable decision auditing and traceability
- Orchestrate complex reasoning workflows

The Trading Agent implements a custom MCP layer that provides three core protocols and an orchestration system. For detailed MCP documentation, see [MCP Layer Documentation](02-mcp-layer.md).

### MCP Architecture Overview

The MCP layer consists of:

1. **MCP Orchestration Layer** - Coordinates all MCP components
2. **MCP Feature Protocol** - Standardized feature communication
3. **MCP Model Protocol** - Standardized model prediction interface
4. **MCP Reasoning Protocol** - Structured reasoning chains

### MCP Orchestration

The MCP Orchestrator coordinates the interaction between all MCP components:

```
MCP Orchestrator
├── MCP Feature Orchestrator
│   └── Feature Server (MCP Feature Protocol)
│       └── Market Data Service
│
├── MCP Model Orchestrator
│   └── Model Registry (MCP Model Protocol)
│       ├── XGBoost Node
│       ├── LSTM Node
│       ├── Transformer Node
│       └── Other Model Nodes
│
└── MCP Reasoning Orchestrator
    └── Reasoning Engine (MCP Reasoning Protocol)
        ├── Uses Feature Server
        ├── Uses Model Registry
        └── Uses Memory Store
```

**Orchestration Flow**:
1. Request arrives at MCP Orchestrator
2. Feature Orchestrator requests features via Feature Protocol
3. Model Orchestrator requests predictions via Model Protocol
4. Reasoning Orchestrator generates reasoning chain via Reasoning Protocol
5. All components work together to produce final decision

For detailed orchestration documentation, see [MCP Layer Documentation - Orchestration](02-mcp-layer.md#mcp-orchestration).

### MCP Components

#### 1. MCP Feature Protocol

**Purpose**: Standardized feature communication with versioning and quality tracking

**Key Features**:
- Semantic versioning for features
- Quality assessment (HIGH, MEDIUM, LOW, DEGRADED)
- Metadata tracking
- Quality score calculation
- Automatic quality monitoring

**Implementation**: `agent/data/feature_server.py`

**Example Structure**:
```python
class MCPFeature(BaseModel):
    name: str
    version: str  # "1.2.3"
    value: float
    timestamp: datetime
    quality: FeatureQuality
    metadata: Dict[str, any]
    computation_time_ms: float
```

For detailed Feature Protocol documentation, see [MCP Layer Documentation - Feature Protocol](02-mcp-layer.md#mcp-feature-protocol).

#### 2. MCP Model Protocol

**Purpose**: Standardized model prediction format with explanations

**Key Features**:
- Consistent prediction format (-1.0 to +1.0)
- Confidence scoring
- Human-readable reasoning (SHAP-based)
- Feature importance tracking
- Model health status
- Automatic model discovery and registration

**Implementation**: `agent/models/mcp_model_registry.py`

**Example Structure**:
```python
class MCPModelPrediction(BaseModel):
    model_name: str
    model_version: str
    prediction: float  # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Human-readable explanation
    features_used: List[str]
    feature_importance: Dict[str, float]
    computation_time_ms: float
    health_status: str
```

For detailed Model Protocol documentation, see [MCP Layer Documentation - Model Protocol](02-mcp-layer.md#mcp-model-protocol).

#### 3. MCP Reasoning Protocol

**Purpose**: Structured reasoning chains for decision transparency

**Key Features**:
- Multi-step reasoning process (6-step chain)
- Evidence tracking
- Confidence calibration
- Decision context preservation
- Integration with Feature and Model Protocols

**Implementation**: `agent/core/reasoning_engine.py`

**Example Structure**:
```python
class MCPReasoningChain(BaseModel):
    chain_id: str
    timestamp: datetime
    market_context: Dict[str, any]
    steps: List[ReasoningStep]
    conclusion: str
    final_confidence: float
    model_predictions: List[MCPModelPrediction]
    feature_context: List[MCPFeature]
```

For detailed Reasoning Protocol documentation, see [MCP Layer Documentation - Reasoning Protocol](02-mcp-layer.md#mcp-reasoning-protocol).

---

## Component Definitions

### Data Layer Components

#### MCP Feature Server
- **Responsibility**: Compute and serve features with quality monitoring
- **Protocol**: MCP Feature Protocol
- **Dependencies**: Market Data Service, TimescaleDB
- **Output**: MCPFeatureResponse with quality scores

#### Market Data Service
- **Responsibility**: Fetch and cache market data from Delta Exchange
- **Protocol**: Delta Exchange REST API
- **Dependencies**: Delta Exchange API, Redis cache
- **Output**: OHLCV data, ticker data

#### Vector Memory Store
- **Responsibility**: Store and retrieve similar decision contexts
- **Protocol**: Vector similarity search
- **Dependencies**: Qdrant/Pinecone, Embedding models
- **Output**: Similar past situations with embeddings

### Intelligence Layer Components

#### MCP Model Registry
- **Responsibility**: Manage all ML model nodes
- **Protocol**: MCP Model Protocol
- **Dependencies**: Model nodes, Performance tracker
- **Output**: Aggregated model predictions

#### MCP Reasoning Engine
- **Responsibility**: Generate structured reasoning chains
- **Protocol**: MCP Reasoning Protocol
- **Dependencies**: Model Registry, Feature Server, Memory Store
- **Output**: Complete reasoning chain with decision

#### Risk Manager
- **Responsibility**: Assess and manage trading risks
- **Protocol**: Internal risk assessment API
- **Dependencies**: Portfolio state, Market data
- **Output**: Risk-adjusted position sizes, stop losses

#### Learning System
- **Responsibility**: Learn from trade outcomes and adapt
- **Protocol**: Internal learning API
- **Dependencies**: Trade outcomes, Model Registry
- **Output**: Model weight updates, strategy adaptations

### Presentation Layer Components

#### FastAPI Backend
- **Responsibility**: Expose REST API and WebSocket endpoints
- **Protocol**: REST API, WebSocket
- **Dependencies**: Agent services, Database, Redis
- **Output**: API responses, WebSocket messages

#### WebSocket Manager
- **Responsibility**: Manage real-time connections
- **Protocol**: WebSocket
- **Dependencies**: FastAPI, Agent services
- **Output**: Real-time updates to clients

#### Next.js Frontend
- **Responsibility**: User interface and visualization
- **Protocol**: HTTP, WebSocket client
- **Dependencies**: Backend API, WebSocket
- **Output**: Interactive dashboard

---

## Integration Points

### Backend ↔ Agent Communication

**Pattern**: Message queue with command/response
- Backend sends commands to agent via queue
- Agent processes and responds via response queue
- Timeout handling for unresponsive agent
- Health check ping mechanism

### Frontend ↔ Backend Communication

**Pattern**: REST API + WebSocket
- REST API for initial data loading
- WebSocket for real-time updates
- Automatic reconnection with exponential backoff
- Message queuing during disconnection

### Agent ↔ Delta Exchange

**Pattern**: REST API with circuit breaker
- Direct API calls to Delta Exchange
- Circuit breaker prevents cascading failures
- Retry logic with exponential backoff
- Health monitoring for API availability

### Agent ↔ Feature Server

**Pattern**: MCP Feature Protocol
- Standardized feature requests via MCP Feature Orchestrator
- Quality-aware feature responses
- Caching for performance
- Version management
- Automatic quality assessment

**Implementation**: MCP Feature Server (`agent/data/feature_server.py`) implements the protocol and is accessed through the MCP Orchestrator.

### Agent ↔ Model Nodes

**Pattern**: MCP Model Protocol
- Parallel model inference via MCP Model Orchestrator
- Standardized prediction format
- Health monitoring per model
- Performance tracking
- Automatic model discovery and registration

**Implementation**: MCP Model Registry (`agent/models/mcp_model_registry.py`) manages all model nodes and implements the protocol. Models are automatically discovered from `agent/model_storage/` directory.

### MCP Layer Integration

**Pattern**: MCP Orchestration
- All MCP components coordinated through MCP Orchestrator
- Feature, Model, and Reasoning protocols work together
- Context maintained across all components
- Decision traceability through reasoning chains

**Implementation**: MCP Orchestrator (`agent/core/mcp_orchestrator.py`) coordinates all MCP components and provides unified interface to the agent core.

---

## Communication Protocols

### REST API Protocol

**Base URL**: `http://localhost:8000/api/v1`

**Endpoints**:
- `GET /health` - System health check
- `POST /predict` - Get AI prediction
- `POST /trade/execute` - Execute trade
- `GET /portfolio/status` - Portfolio status
- `GET /portfolio/performance` - Performance metrics

**Request Format**: JSON
**Response Format**: JSON with standardized error format

### WebSocket Protocol

**Connection**: `ws://localhost:8000/ws`

**Message Types**:
- `agent_state` - Agent state updates
- `trade_executed` - New trade notifications
- `portfolio_update` - Portfolio value changes
- `health_status` - Health status changes
- `prediction_generated` - New prediction available

**Client Actions**:
- `subscribe` - Subscribe to channels
- `get_state` - Request current state

### MCP Protocol

**Feature Request**:
```json
{
  "feature_names": ["rsi_14", "macd_signal"],
  "version": "latest",
  "symbol": "BTCUSD",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

**Model Request**:
```json
{
  "request_id": "req_123",
  "features": [...],
  "context": {...},
  "require_explanation": true
}
```

**Reasoning Chain**:
```json
{
  "chain_id": "chain_456",
  "steps": [...],
  "conclusion": "...",
  "final_confidence": 0.75
}
```

---

## Error Handling Strategy

### Graceful Degradation

The system implements graceful degradation at multiple levels:

1. **Feature Quality Degradation**
   - Low quality features are flagged but still used
   - Degraded features reduce overall quality score
   - System continues operating with reduced confidence

2. **Model Node Degradation**
   - Failed models are excluded from consensus
   - Remaining models continue operating
   - System status set to "degraded" if <3 models healthy

3. **Service Degradation**
   - Database failures: Use cached data
   - Redis failures: Direct database access
   - Delta Exchange failures: Circuit breaker opens, no trading

### Circuit Breakers

**Purpose**: Prevent cascading failures and enable graceful degradation

**Circuit Breaker States**:
- **CLOSED**: Normal operation, requests pass through
- **OPEN**: Service failing, requests blocked immediately
- **HALF_OPEN**: Testing if service recovered, limited requests allowed

**Implementation Details**:
- **Failure Threshold**: 5 consecutive failures trigger OPEN state
- **Timeout**: 60 seconds before transitioning to HALF_OPEN
- **Success Threshold**: 2 successful requests in HALF_OPEN to return to CLOSED
- **Metric Integration**: Failure and success counters feed Prometheus metrics so dashboards expose breaker state (`mcp_circuit_breaker_state{component="delta_exchange"}`).
- **Alert Hooks**: When a breaker flips OPEN, the notification layer publishes a `system.alert` log entry and optionally calls the on-call webhook documented in [Logging Documentation](12-logging.md#observability-integration).
- **Partial Failure Handling**: System continues with reduced capabilities when circuit breaker opens. Each breaker reports a `degraded_capabilities` payload describing which fallbacks are active (e.g., cached order book, stale features).

**Circuit Breaker Locations**:
- **Delta Exchange API**: Prevents cascading failures from exchange issues
- **Database Connections**: Protects against database overload
- **Redis Operations**: Handles Redis failures gracefully
- **Model Inference Calls**: Prevents model failures from blocking system

**Recovery Mechanism**:
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.success_count = 0  # Initialize success_count for HALF_OPEN state tracking
        self.state = "CLOSED"
        self.last_failure_time = None
        self.failure_threshold = failure_threshold
        self.timeout = timeout
    
    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                self.success_count = 0  # Reset success count when entering HALF_OPEN
            else:
                raise CircuitBreakerOpenError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.success_count += 1
                if self.success_count >= 2:
                    self.state = "CLOSED"
                    self.failure_count = 0
                    self.success_count = 0  # Reset success count when closing circuit
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
            raise
```

**Partial Failure Handling**:
When a circuit breaker opens:
- System continues operating with available services
- Degraded mode activated for affected component
- Health score reduced to reflect degradation
- Automatic recovery when service restored

**Operational Checklist**:

| Component              | On Open Action                                                          | Fallback Strategy                                   |
|------------------------|-------------------------------------------------------------------------|-----------------------------------------------------|
| `delta_exchange`       | Pause trade execution, emit `trade_execution_disabled` event            | Use cached quotes for display only                  |
| `model_inference`      | Remove unhealthy models from consensus, log degraded ensemble status    | Rebalance weights to healthy models automatically   |
| `feature_server`       | Lower feature quality score, flag reasoning engine to reduce confidence | Serve last-known-good feature snapshot with TTL     |
| `database`             | Switch reads to replica, throttle write-heavy endpoints                 | Queue writes in Redis buffer until circuit closes   |

Include the checklist in runbooks so operators know which mitigation should trigger automatically and which ones need manual verification.

### Error Response Format

**Standard Error Response**:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {
      "key": "value"
    },
    "timestamp": "2025-01-12T10:30:00Z",
    "request_id": "req_xyz789"
  }
}
```

### Health Check Strategy

**Comprehensive Health Checks**:
- Test actual service availability (not just connection)
- Measure latency for each service
- Calculate numerical health score (0.0 to 1.0)
- Provide degradation reasons

**Health Score Calculation**:
- Weighted average of component health
- Component weights:
  - Feature Server: 20%
  - Model Nodes: 25%
  - Reasoning Engine: 20%
  - Decision Store: 10%
  - Delta Exchange: 15%
  - Database: 5%
  - Redis: 5%

**Status Determination**:
- Healthy: health_score >= 0.9
- Degraded: 0.6 <= health_score < 0.9
- Unhealthy: health_score < 0.6

---

## Data Flow

### Prediction Flow

```
1. Market Data Service → Fetch current ticker
2. Feature Server → Compute features
3. Model Registry → Get predictions from all models
4. Reasoning Engine → Generate reasoning chain
5. Risk Manager → Assess risks
6. Decision Engine → Synthesize decision
7. Backend API → Return prediction to client
8. WebSocket → Broadcast update
```

### Trade Execution Flow

**Entry Flow:**
```
1. Decision Engine → Generate trade decision
2. Risk Manager → Validate risk limits
3. Execution Engine → Place order via Delta Exchange
4. Order Management → Track order status
5. Position Manager → Update positions (with stop loss/take profit)
6. State Machine → Transition to MONITORING_POSITION
7. WebSocket → Broadcast trade execution
8. Database → Store trade record
```

**Exit Flow:**
```
1. Market Data Service → Emit MarketTickEvent on price updates
2. Risk Manager → Check exit conditions (stop loss/take profit)
3. Risk Manager → Emit exit DecisionReadyEvent when condition met
4. Execution Engine → Execute exit trade (opposite side)
5. Execution Engine → Emit PositionClosedEvent with PnL
6. State Machine → Transition MONITORING_POSITION → OBSERVING
7. Learning System → Record trade outcome for learning
8. WebSocket → Broadcast position closed
9. Database → Update trade record with exit details
```

### Learning Flow

```
1. Trade completes → Outcome recorded
2. Learning System → Analyze outcome
3. Model Performance Tracker → Update model weights
4. Confidence Calibrator → Update calibration data
5. Strategy Adapter → Adjust parameters if needed
6. Memory Store → Store decision with embedding
7. Performance Metrics → Update statistics
```

---

## Scalability Considerations

### Horizontal Scaling

- **Backend API**: Stateless, can scale horizontally
- **Agent Core**: Single instance (stateful)
- **Model Nodes**: Can be containerized and scaled
- **Database**: Read replicas for queries

### Performance Optimization

- **Feature Caching**: 60-second TTL in Redis
- **Parallel Model Inference**: asyncio.gather for concurrent predictions
- **Database Indexing**: Indexed on timestamps, decision_ids
- **WebSocket Connection Pooling**: Reuse connections

### Resource Requirements

**Minimum**:
- 4 CPU cores
- 8GB RAM
- 50GB storage

**Recommended**:
- 8 CPU cores
- 16GB RAM
- 100GB storage (for historical data)

---

## Security Considerations

### Authentication

- JWT tokens for API access
- WebSocket authentication via token
- API key for Delta Exchange

### Data Protection

- Encrypted database connections
- Secure environment variable storage
- No sensitive data in logs
- API rate limiting

### Access Control

- Role-based access control (RBAC)
- Admin endpoints protected
- Read-only vs write access separation

---

## Recent Architectural Enhancements

As of 2025-01-27, the system has undergone major architectural improvements. For a complete change log, see [Major Changes Summary](../../MAJOR_CHANGES.md).

### Docker Containerization

The system now supports full containerization for production and development:

- **Production Dockerfiles** (`Dockerfile`) - Optimized multi-stage builds for all services
- **Development Dockerfiles** (`Dockerfile.dev`) - Hot-reload enabled for faster iteration
- **Docker Compose** - Orchestration for backend, agent, frontend, PostgreSQL, and Redis
- **Volume Management** - Persistent storage for databases, logs, and model files
- **Health Checks** - Built-in health monitoring for all containerized services
- **Resource Limits** - CPU and memory constraints for production stability

See [Deployment Documentation](10-deployment.md) for Docker setup and usage instructions.

### CI/CD Pipeline

Automated continuous integration and deployment:

- **GitHub Actions Workflow** (`.github/workflows/cicd.yml`) - Automated testing and deployment
- **Automated Testing** - Python pytest for backend/agent, Jest for frontend
- **Code Quality Checks** - Linting (ruff, black, ESLint) and type checking (mypy, TypeScript)
- **Docker Image Building** - Automated builds pushed to GitHub Container Registry (GHCR)
- **Automated Deployment** - SSH-based deployment to production servers
- **Multi-Service Matrix Builds** - Parallel builds for backend, agent, and frontend

### Event-Driven Architecture

Decoupled component communication through an event bus system:

- **Event Bus** (`agent/events/event_bus.py`) - Central event routing and distribution
- **Event Handlers** - Specialized handlers for features, market data, models, and reasoning
- **Event Schemas** - Typed event definitions for type safety
- **Decoupled Communication** - Components communicate via events rather than direct calls
- **Asynchronous Processing** - Non-blocking event processing for better performance

This architecture enables better scalability, testability, and maintainability by reducing tight coupling between components.

---

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - Detailed MCP architecture and orchestration
- [ML Models Documentation](03-ml-models.md) - Model management and intelligence
- [Features Documentation](04-features.md) - What the system does
- [Logic & Reasoning Documentation](05-logic-reasoning.md) - How decisions are made
- [Backend Documentation](06-backend.md) - API implementation
- [Frontend Documentation](07-frontend.md) - UI implementation
- [Deployment Documentation](10-deployment.md) - Setup and deployment
- [Build Guide](11-build-guide.md) - Complete build instructions
- [Major Changes Summary](../../MAJOR_CHANGES.md) - Detailed change log for recent architectural improvements

