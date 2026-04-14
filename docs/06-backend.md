# Backend Documentation

## Overview

The backend is built using **FastAPI** and provides REST API endpoints, WebSocket support, and integration with the AI agent core. This document covers the backend architecture, API specifications, and implementation details.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [FastAPI Application Structure](#fastapi-application-structure)
- [REST API Endpoints](#rest-api-endpoints)
- [WebSocket Protocol](#websocket-protocol)
- [Database Models](#database-models)
- [Service Layer Architecture](#service-layer-architecture)
- [Error Handling](#error-handling)
- [Middleware](#middleware)
- [Logging & Observability](#logging--observability)
- [Configuration](#configuration)
- [Command Operations](#command-operations)
- [MCP Layer Integration](#mcp-layer-integration)
- [Related Documentation](#related-documentation)

---

## FastAPI Application Structure

### Directory Layout

```
backend/
├── api/
│   ├── main.py                 # FastAPI app initialization
│   ├── routes/
│   │   ├── health.py           # Health and status endpoints
│   │   ├── ml_signal.py        # Model status + v15 edge history (Redis)
│   │   ├── trading.py          # Trading operations
│   │   ├── portfolio.py        # Portfolio queries
│   │   ├── market.py           # Market data endpoints
│   │   └── admin.py            # Manual controls
│   ├── middleware/
│   │   ├── auth.py             # JWT authentication
│   │   ├── rate_limit.py       # Rate limiting
│   │   ├── cors.py             # CORS configuration
│   │   └── logging.py          # Request logging
│   ├── models/
│   │   ├── requests.py         # Pydantic request models
│   │   └── responses.py        # Pydantic response models
│   └── websocket/
│       └── manager.py          # WebSocket connection manager
├── services/
│   ├── agent_service.py        # Agent communication
│   ├── market_service.py       # Market data fetching
│   ├── portfolio_service.py    # Portfolio calculations
│   └── feature_service.py      # MCP Feature Server client
└── core/
    ├── config.py               # Configuration management
    ├── database.py             # Database connection
    └── redis.py                # Redis connection
```

---

## REST API Endpoints

### Base URL

All API endpoints are prefixed with `/api/v1`

### Health & Status

#### GET `/api/v1/health`

Comprehensive health check endpoint that tests all services.

**Response**:
```json
{
  "status": "healthy" | "degraded" | "unhealthy",
  "health_score": 0.95,
  "services": {
    "database": {
      "status": "up",
      "latency_ms": 5.2
    },
    "redis": {
      "status": "up",
      "latency_ms": 2.1
    },
    "agent": {
      "status": "up",
      "state": "MONITORING",
      "last_heartbeat": "2025-01-12T10:30:00Z"
    },
    "delta_exchange": {
      "status": "up",
      "latency_ms": 150.3
    },
    "feature_server": {
      "status": "up",
      "feature_quality": 0.92,
      "latency_ms": 45.7
    },
    "model_nodes": {
      "status": "up",
      "healthy_models": 5,
      "total_models": 5
    }
  },
  "agent_state": "MONITORING",
  "degradation_reasons": [],
  "timestamp": "2025-01-12T10:30:00Z"
}
```

#### Model Nodes Troubleshooting

When the dashboard shows `model_nodes: UNKNOWN`, the backend is intentionally reporting that the agent cannot confirm any active ML models. Common scenarios:

- **Discovery disabled** – No model directory is configured and discovery was never attempted.
- **No model files found** – Discovery ran but `MODEL_DIR` was empty.
- **Failed models** – Discovery attempted to load files but all failed validation.
- **Agent unavailable** – The backend could not reach the agent process.

Use these steps to recover:

1. Ensure the desired `.pkl`/model artifacts exist under `agent/model_storage` (or the path pointed to by `MODEL_DIR`/`MODEL_PATH`).
2. Restart the agent or trigger manual discovery so `_handle_get_status` can rebuild the registry.
3. Tail the agent logs for the new structured events:
   - `model_nodes_discovery_result` – Emitted whenever discovery completes with zero loaded models. Includes `discovery_reason`, `failed_models`, and `total_models`.
   - `model_nodes_status_missing` – Emitted when the agent cannot read registry health at all.
4. Re-run `GET /api/v1/health` or refresh the dashboard to confirm the `model_nodes` entry now reports precise counts.

These log lines surface the exact remediation hint (`note`) that is also forwarded to the frontend `HealthMonitor`, allowing operators to correlate dashboard status with agent logs.

**Status Codes**:
- `200`: Success
- `503`: Service unavailable (unhealthy)

Health responses may include an optional **`ml_models`** summary when the agent exposes model-node details (see `backend/api/routes/health.py`).

#### GET `/api/v1/models/status`

Proxies agent registry summary via `agent_service.get_agent_status()`.

**Response** (shape is best-effort; fields depend on agent version):

```json
{
  "available": true,
  "agent_state": "MONITORING",
  "model_nodes": {
    "status": "up",
    "healthy_models": 2,
    "total_models": 2,
    "model_format": "auto",
    "discovery": {}
  },
  "model_format": "auto",
  "latency_ms": 12.3,
  "status_stale": false
}
```

#### GET `/api/v1/signal/edge-history`

Query params: `symbol` (default `BTCUSD`), `limit` (1–200, default 50).

Returns recent **v15 edge** samples appended by `agent_event_subscriber` to Redis (`jacksparrow:v15:edge_history:{symbol}`) when WebSocket signal payloads include `edge`.

```json
{
  "symbol": "BTCUSD",
  "edges": [{ "ts": "...", "edge": 0.21, "signal": "BUY", "timeframe": "5m" }],
  "count": 1
}
```

### Perpetual Futures Market API

#### GET `/api/v1/market/perpetual-stats`

Returns perpetual futures symbol stats for agent risk and feature decisions.

Response:
```json
{
  "symbol": "BTCUSD",
  "mark_price": 51240.5,
  "index_price": 51200.9,
  "basis": 39.6,
  "basis_pct": 0.077,
  "funding_rate": -0.00012,
  "funding_timestamp": "2026-04-02T12:00:00Z",
  "open_interest": 350000000.0,
  "oi_change_pct_1h": 0.8,
  "bid_ask_imbalance": 0.042
}
```

Status Codes:
- `200`: Success
- `400`: Invalid symbol
- `503`: Market unavailable

#### GET `/api/v1/market/funding-history`

Query params:
- `symbol` (required)
- `limit` (optional, default 24)

Response:
```json
{
  "symbol": "BTCUSD",
  "funding_history": [
    {"timestamp": "2026-04-02T04:00:00Z", "funding_rate": -0.00012},
    {"timestamp": "2026-04-01T20:00:00Z", "funding_rate": -0.00010}
  ]
}
```

Status Codes:
- `200`: Success
- `400`: Invalid parameters
- `503`: Market unavailable

---

### Trading Operations

#### POST `/api/v1/predict`

Request AI prediction for current market conditions.

**Request Parameters**:
- `symbol` (query, optional): Trading symbol (default: "BTCUSD")

**Example**:

```bash
curl -X POST "http://localhost:8000/api/v1/predict?symbol=BTCUSD" \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response**:
```json
{
  "signal": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
  "confidence": 0.75,
  "position_size": 0.05,
  "reasoning_chain": {
    "chain_id": "chain_123",
    "steps": [
      {
        "step": 1,
        "thought": "SITUATION ASSESSMENT: Market regime: bull_trending...",
        "confidence": 0.85,
        "evidence": ["feature:rsi_14=65.2", "feature:macd_signal=0.5"]
      },
      // ... more steps
    ],
    "conclusion": "After analyzing the current situation...",
    "final_confidence": 0.75
  },
  "model_predictions": [
    {
      "model": "xgboost",
      "prediction": 0.8,
      "confidence": 0.85,
      "reasoning": "Model predicts BULLISH signal...",
      "features_used": ["rsi_14", "macd_signal", "volume_ratio"]
    },
    // ... more models
  ],
  "risk_assessment": {
    "risk_level": 0.25,
    "portfolio_heat": 0.15,
    "recommended_position_multiplier": 0.75,
    "stop_loss_percentage": 2.0
  },
  "timestamp": "2025-01-12T10:30:00Z"
}
```

**Status Codes**:
- `200`: Success
- `500`: Internal server error
- `503`: Agent unavailable

---

#### POST `/api/v1/trade/execute`

Execute a trade (manual or agent-initiated).

**Request Body**:
```json
{
  "symbol": "BTCUSD",
  "side": "buy" | "sell",
  "position_size": 0.05,
  "order_type": "market" | "limit",
  "price": 50000.0,
  "stop_loss": 49000.0,
  "take_profit": 51000.0
}
```

**Response**:
```json
{
  "order_id": "order_abc123",
  "status": "filled" | "pending" | "rejected",
  "executed_price": 50100.0,
  "quantity": 0.05,
  "symbol": "BTCUSD",
  "side": "buy",
  "timestamp": "2025-01-12T10:30:00Z",
  "reason": "Order executed successfully"
}
```

**Status Codes**:
- `200`: Success
- `400`: Bad request (invalid parameters, insufficient balance)
- `403`: Forbidden (operation not allowed in current state)
- `500`: Internal server error

**Error Response**:
```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Insufficient balance for trade",
    "details": {
      "required": 5000.0,
      "available": 3000.0
    },
    "timestamp": "2025-01-12T10:30:00Z",
    "request_id": "req_xyz789"
  }
}
```

---

### Portfolio Management

#### GET `/api/v1/portfolio/status`

Get current portfolio status.

**Response**:
```json
{
  "total_value": 100000.0,
  "cash": 95000.0,
  "positions_value": 5000.0,
  "unrealized_pnl": 500.0,
  "realized_pnl": 1500.0,
  "positions": [
    {
      "symbol": "BTCUSD",
      "quantity": 0.1,
      "entry_price": 49000.0,
      "current_price": 50000.0,
      "unrealized_pnl": 100.0,
      "entry_time": "2025-01-12T09:00:00Z",
      "duration_minutes": 90
    }
  ],
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

#### GET `/api/v1/portfolio/performance`

Get portfolio performance metrics.

**Query Parameters**:
- `period` (optional): "1d" | "7d" | "30d" | "all" (default: "all")

**Response**:
```json
{
  "total_return": 0.02,
  "total_return_percent": 2.0,
  "sharpe_ratio": 1.5,
  "sortino_ratio": 2.1,
  "max_drawdown": 0.05,
  "win_rate": 0.65,
  "total_trades": 150,
  "winning_trades": 98,
  "losing_trades": 52,
  "avg_trade_return": 0.015,
  "avg_winning_trade": 0.025,
  "avg_losing_trade": -0.012,
  "profit_factor": 2.08,
  "period": "all",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

#### GET `/api/v1/portfolio/trades`

Get trade history.

**Query Parameters**:
- `limit` (optional): Number of trades to return (default: 50, max: 500)
- `offset` (optional): Pagination offset (default: 0)
- `symbol` (optional): Filter by symbol
- `status` (optional): "open" | "closed"

**Response**:
```json
{
  "trades": [
    {
      "trade_id": "trade_123",
      "decision_id": "decision_456",
      "symbol": "BTCUSD",
      "side": "buy",
      "quantity": 0.1,
      "entry_price": 49000.0,
      "exit_price": 50000.0,
      "entry_time": "2025-01-12T09:00:00Z",
      "exit_time": "2025-01-12T10:00:00Z",
      "duration_minutes": 60,
      "pnl": 100.0,
      "pnl_percent": 0.02,
      "status": "closed",
      "exit_reason": "take_profit"
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

---

### Market Data

#### GET `/api/v1/market/ticker`

Get current ticker data.

**Query Parameters**:
- `symbol` (required): Trading symbol (e.g., "BTCUSD")

**Response**:
```json
{
  "symbol": "BTCUSD",
  "last_price": 50000.0,
  "bid": 49999.0,
  "ask": 50001.0,
  "volume_24h": 1000.5,
  "high_24h": 51000.0,
  "low_24h": 49000.0,
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

#### GET `/api/v1/market/features`

Get current feature values.

**Query Parameters**:
- `symbol` (required): Trading symbol
- `version` (optional): Feature version (default: "latest")

**Response**:
```json
{
  "symbol": "BTCUSD",
  "features": [
    {
      "name": "rsi_14",
      "version": "1.0.0",
      "value": 65.2,
      "quality": "HIGH",
      "timestamp": "2025-01-12T10:30:00Z"
    },
    // ... more features
  ],
  "quality_score": 0.92,
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

### Admin Operations

#### POST `/api/v1/admin/agent/start`

Start the trading agent.

**Response**:
```json
{
  "status": "started",
  "agent_state": "MONITORING",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

#### POST `/api/v1/admin/agent/stop`

Stop the trading agent.

**Response**:
```json
{
  "status": "stopped",
  "agent_state": "STOPPED",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

#### POST `/api/v1/admin/agent/emergency-stop`

Emergency stop - immediately halt all trading.

**Response**:
```json
{
  "status": "emergency_stopped",
  "agent_state": "EMERGENCY_STOP",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

## WebSocket Protocol

### Connection Endpoints

**Frontend Client Endpoint**: `ws://localhost:8000/ws`
- Used by frontend for real-time updates
- **Simplified Format**: Uses 3 core message types (`data_update`, `agent_update`, `system_update`)
- **Details**: [Simplified Message Format](#simplified-message-format) below and [Frontend WebSocket Integration](07-frontend.md#websocket-integration)

**Agent Event Endpoint**: `ws://localhost:8000/ws/agent`
- Used by agent to send events directly to backend
- Lower latency than Redis Streams
- Backend routes agent events to frontend clients

**Authentication**: Token-based (optional for development)

### Simplified Message Format

All WebSocket messages use a unified envelope format:

```json
{
  "type": "data_update" | "agent_update" | "system_update",
  "resource": "signal" | "portfolio" | "trade" | "market" | "model" | "agent" | "health" | "time",
  "data": { ... },
  "timestamp": "2025-01-12T10:30:00Z",
  "sequence": 12345,
  "source": "agent" | "system",
  "server_timestamp_ms": 1706356800123
}
```

### Message Types

#### Server → Client Messages

**Agent State Update** (`agent_update`):
```json
{
  "type": "agent_update",
  "resource": "agent",
  "data": {
    "state": "ANALYZING",
    "message": "Processing new market data",
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "agent"
}
```

**Trade Executed** (`data_update` with `resource: "trade"`):
```json
{
  "type": "data_update",
  "resource": "trade",
  "data": {
    "order_id": "order_abc123",
    "symbol": "BTCUSD",
    "side": "buy",
    "price": 50000.0,
    "quantity": 0.05,
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "system"
}
```

**Portfolio Update** (`data_update` with `resource: "portfolio"`):
```json
{
  "type": "data_update",
  "resource": "portfolio",
  "data": {
    "total_value": 100500.0,
    "unrealized_pnl": 500.0,
    "cash": 95000.0,
    "positions_value": 5000.0,
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "system"
}
```

**Health Status Change** (`system_update` with `resource: "health"`):
```json
{
  "type": "system_update",
  "resource": "health",
  "data": {
    "status": "degraded",
    "health_score": 0.72,
    "reason": "Delta Exchange API latency high",
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "system"
}
```

**Signal Update** (`data_update` with `resource: "signal"`):
```json
{
  "type": "data_update",
  "resource": "signal",
  "data": {
    "signal": "BUY",
    "confidence": 0.75,
    "symbol": "BTCUSD",
    "model_consensus": [...],
    "reasoning_chain": [...],
    "individual_model_reasoning": [...],
    "agent_decision_reasoning": "Market shows bullish trend...",
    "timestamp": "2025-01-12T10:30:00Z"
  }
}
```

**v15 extensions** (optional on the same `signal` payload when v15 models produced the strongest edge):

| Field | Description |
|-------|-------------|
| `edge` | `p_buy − p_sell` from the selected v15 prediction |
| `p_buy`, `p_sell`, `p_hold` | Class probabilities from model context |
| `v15_timeframe` | `5m` or `15m` for that prediction |

Per-model `model_consensus[]` entries may also include `p_buy`, `p_sell`, `p_hold`, `edge`, and `timeframe` when `context.format === "v15_pipeline"`.

**Reasoning Chain Update** (`data_update` with `resource: "signal"`):
```json
{
  "type": "data_update",
  "resource": "signal",
  "data": {
    "symbol": "BTCUSD",
    "reasoning_chain": [
      {
        "step_number": 1,
        "description": "Situational assessment...",
        "confidence": 0.8
      }
    ],
    "conclusion": "Final decision reasoning...",
    "final_confidence": 0.75,
    "chain_id": "chain_123",
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "agent"
}
```

**Model Prediction Update** (`data_update` with `resource: "model"`):
```json
{
  "type": "data_update",
  "resource": "model",
  "data": {
    "symbol": "BTCUSD",
    "consensus_signal": "BUY",
    "signal": "BUY",
    "consensus_confidence": 0.825,
    "model_consensus": [
      {
        "model_name": "xgboost_v1",
        "signal": "BUY",
        "confidence": 0.85,
        "prediction": 0.8,
        "p_buy": 0.52,
        "p_sell": 0.21,
        "p_hold": 0.27,
        "edge": 0.31,
        "timeframe": "5m"
      }
    ],
    "individual_model_reasoning": [
      {
        "model_name": "xgboost_v1",
        "reasoning": "RSI indicates oversold...",
        "confidence": 0.85,
        "prediction": 0.8
      }
    ],
    "timestamp": "2025-01-12T10:30:00Z"
  }
}
```

**Note:** `consensus_signal` is mapped from numeric (-1 to +1) to discrete string (STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL). Per-model `confidence` values are normalized to 0.0-1.0 range.

**Market Tick Update**:
```json
{
  "type": "market_tick",
  "data": {
    "symbol": "BTCUSD",
    "price": 50000.0,
    "volume": 1234.56,
    "timestamp": "2025-01-12T10:30:00Z"
  },
  "timestamp": "2025-01-12T10:30:00Z",
  "source": "agent"
}
```

**Note**: Legacy message types are normalized to the unified envelope; map old types to `data_update` / `agent_update` / `system_update` plus `resource` (see table in [Frontend](07-frontend.md#simplified-websocket-message-format)).

#### Client → Server Messages

**Subscribe to Channels**:
```json
{
  "action": "subscribe",
  "channels": ["trades", "portfolio", "agent_state", "health"]
}
```

**Request Current State**:
```json
{
  "action": "get_state"
}
```

**Unsubscribe from Channels**:
```json
{
  "action": "unsubscribe",
  "channels": ["health"]
}
```

#### Agent → Backend Messages (via `/ws/agent`)

**Agent Event**:
```json
{
  "type": "agent_event",
  "event_type": "decision_ready|state_transition|order_fill|...",
  "payload": {
    "symbol": "BTCUSD",
    "signal": "BUY",
    "confidence": 0.75,
    ...
  },
  "event_id": "uuid",
  "correlation_id": "uuid",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

**Event Deduplication:** The backend extracts `event_id` from the top level of the event (not from `payload`) for deduplication. Duplicate events (e.g., from Redis Streams and WebSocket) are skipped using Redis key `processed_event:{event_id}` with 5-minute TTL.

**Position-Closed Handling:** When a position is closed, the backend broadcasts only the full portfolio update (not a partial `{position_closed: {...}}` message). This ensures the frontend never receives an incomplete portfolio that would cause UI flicker.

**Ping**:
```json
{
  "type": "ping",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

#### Backend → Agent Messages (via Agent WebSocket Server)

**Command**:
```json
{
  "type": "command",
  "request_id": "uuid",
  "command": "predict|execute_trade|get_status|control",
  "parameters": {}
}
```

**Ping**:
```json
{
  "type": "ping",
  "request_id": "uuid"
}
```

#### Agent → Backend Response Messages

**Response**:
```json
{
  "type": "response",
  "request_id": "uuid",
  "success": true,
  "data": {},
  "timestamp": "2025-01-12T10:30:00Z"
}
```

**Error**:
```json
{
  "type": "error",
  "request_id": "uuid",
  "success": false,
  "error": "Error message",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

**Pong**:
```json
{
  "type": "pong",
  "request_id": "uuid",
  "timestamp": "2025-01-12T10:30:00Z"
}
```

---

### Data Freshness Protocol

The backend implements a comprehensive data freshness protocol to ensure frontend clients receive timely updates with accurate timestamps.

#### Server Timestamp Injection

All WebSocket messages broadcast via `websocket_manager.broadcast()` automatically receive server-side timestamps:

```json
{
  "type": "message_type",
  "data": {
    "field1": "value1",
    "timestamp": "2025-01-27T12:00:00Z"
  },
  "server_timestamp": "2025-01-27T12:00:00.123Z",
  "server_timestamp_ms": 1706356800123
}
```

**Fields**:
- `server_timestamp`: ISO 8601 formatted server time when message was broadcast
- `server_timestamp_ms`: Unix timestamp in milliseconds for precise age calculation
- `data.timestamp`: Event-specific timestamp (when the event occurred)

**Implementation**: The `WebSocketManager.broadcast()` method automatically injects these timestamps using `time_service.get_time_info()` before sending messages to clients.

#### Message-Level Timestamps

All event handlers in `agent_event_subscriber.py` add `timestamp` fields to their message data:

- `data_update` (resource: `market`): Includes timestamp from market data event
- `data_update` (resource: `signal`): Includes timestamp from decision ready event
- `data_update` (resource: `model`): Includes timestamp from model prediction event
- `data_update` (resource: `portfolio`): Includes current UTC timestamp
- `data_update` (resource: `trade`): Includes execution timestamp
- `agent_update`: Includes timestamp from state transition or periodic sync
- `system_update` (resource: `health`): Includes health check timestamp
- `system_update` (resource: `time`): Includes server time synchronization

#### Periodic Update Frequencies

The backend maintains several periodic sync loops to ensure fresh data:

1. **Agent State Sync** (`_agent_state_sync_loop`):
   - Frequency: Every 30 seconds
   - Purpose: Broadcast current agent state even when idle
   - Ensures frontend always has up-to-date agent status

2. **Health Status Sync** (`_health_sync_loop`):
   - Frequency: Every 60 seconds
   - Purpose: Broadcast system health status
   - Includes all service health checks

3. **Time Sync** (`_time_sync_loop`):
   - Frequency: Every 30 seconds
   - Purpose: Synchronize client clocks with server time
   - Helps with accurate freshness calculations

4. **Market Ticks**:
   - Frequency: Every 5 seconds (time-based fallback) OR on price change >0.01%
   - Purpose: Provide real-time price updates
   - Ensures frequent updates even during low volatility

5. **Portfolio Updates**:
   - Triggered: On market tick or trade execution
   - Purpose: Keep portfolio data synchronized with market changes

#### Timestamp Format

All timestamps use ISO 8601 format:
- **Backend sends**: `YYYY-MM-DDTHH:mm:ss.sss` (UTC, no timezone suffix)
- **Example**: `2025-01-27T12:00:00.123456` (from `datetime.utcnow().isoformat()`)
- **Frontend normalizes**: Appends 'Z' to treat as UTC: `2025-01-27T12:00:00.123456Z`
- **Display format**: Converted to IST (Asia/Kolkata) and displayed as `HH:mm:ss am/pm`
- Milliseconds included for precision
- Frontend assumes UTC when timezone is missing (standard practice)

#### Freshness Calculation

Frontend calculates data freshness using:
1. Primary: `data.timestamp` (event-specific timestamp)
2. Fallback: `server_timestamp_ms` (server broadcast time)
3. Age calculation: `current_time - timestamp`
4. Color coding:
   - Green: < 1 minute old (fresh)
   - Amber: 1-5 minutes old (stale)
   - Red: > 5 minutes old (very stale)

---

## Database Models

### Trade Model

```python
class Trade(Base):
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(String, unique=True, index=True)
    decision_id = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    symbol = Column(String)
    side = Column(String)  # 'buy' or 'sell'
    quantity = Column(Float)
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    entry_time = Column(DateTime)
    exit_time = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    status = Column(String)  # 'open', 'closed'
    exit_reason = Column(String, nullable=True)
    
    # AI-related fields
    reasoning_chain = Column(JSON)
    model_predictions = Column(JSON)
    confidence = Column(Float)
```

### Decision Memory Model

```python
class DecisionMemory(Base):
    __tablename__ = 'decision_memory'
    
    id = Column(Integer, primary_key=True)
    decision_id = Column(String, unique=True, index=True)
    timestamp = Column(DateTime, index=True)
    context = Column(JSON)
    reasoning_chain = Column(JSON)
    decision = Column(JSON)
    outcome = Column(JSON, nullable=True)
    embedding = Column(JSON)  # Vector embedding as JSON array
```

### Model Performance Model

```python
class ModelPerformance(Base):
    __tablename__ = 'model_performance'
    
    id = Column(Integer, primary_key=True)
    model_name = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    accuracy = Column(Float)
    sharpe_ratio = Column(Float)
    win_rate = Column(Float)
    avg_contribution = Column(Float)
    current_weight = Column(Float)
```

---

## Service Layer Architecture

### Agent Service

**Purpose**: Communication bridge between backend API and agent core.

**Key Methods**:
- `request_prediction(symbol)`: Request prediction from agent
- `execute_trade(trade_request)`: Execute trade via agent
- `get_state()`: Get current agent state
- `start_agent()`: Start the agent
- `stop_agent()`: Stop the agent

**Implementation Pattern**: Message queue with timeout handling

### Market Service

**Purpose**: Fetch and cache market data.

**Key Methods**:
- `get_ticker(symbol)`: Get current ticker
- `get_historical_data(symbol, period)`: Get historical OHLCV
- `cache_ticker(symbol, data)`: Cache ticker data

**Caching Strategy**: Redis with 60-second TTL

### Portfolio Service

**Purpose**: Calculate portfolio metrics and status.

**Key Methods**:
- `get_portfolio_status()`: Get current portfolio status
- `calculate_performance(period)`: Calculate performance metrics
- `get_trade_history(limit, offset)`: Get trade history
- `get_usdinr_rate()` path: use market-fed cached USDINR first, then last-good/static fallback for INR portfolio/PnL conversion

**Currency contract (Phase 1)**:
- BTCUSD market prices remain USD in market payloads (`price`, `entry_price`, `current_price`)
- Portfolio balances/PnL are emitted in INR (`total_value`, `available_balance`, `margin_used`, `total_unrealized_pnl`, `total_realized_pnl`)
- **Margin and ROE (frontend)**: `margin_used` is the sum of **isolated margin in USD** per open position (`notional_usd / leverage` using `contract_value_btc` and `isolated_margin_leverage` from settings), converted to INR with the **same** `get_usdinr_rate()` snapshot as unrealized PnL so **ROE ratios** (unrealized ÷ margin) are not distorted by mixing FX sources. Leverage is **config-based**, not necessarily the exchange UI — optional future reconciliation with Delta `GET /v2/positions`. Multi-asset: one global `contract_value_btc` in `get_portfolio_summary` assumes a single contract spec unless extended per symbol.

### Feature Service

**Purpose**: Access MCP Feature Server via MCP Feature Protocol.

**Key Methods**:
- `get_features(symbol, version)`: Get features from MCP Feature Server
- `cache_features(symbol, features)`: Cache features
- `get_feature_quality(symbol)`: Get feature quality scores

**MCP Integration**: The Feature Service communicates with the MCP Feature Server using the MCP Feature Protocol. All feature requests and responses follow the standardized `MCPFeature` and `MCPFeatureResponse` formats.

**Caching Strategy**: Redis with 60-second TTL

For detailed MCP Feature Protocol documentation, see [MCP Layer Documentation - Feature Protocol](02-mcp-layer.md#mcp-feature-protocol).

---

## Error Handling

### Standard Error Response Format

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {
      "key": "value"
    },
    "timestamp": "2025-01-12T10:30:00Z",
    "request_id": "req_xyz789"
  }
}
```

### HTTP Status Codes

- `200`: Success
- `400`: Bad request (invalid parameters)
- `401`: Unauthorized (invalid API key)
- `403`: Forbidden (operation not allowed in current state)
- `404`: Not found
- `429`: Too many requests (rate limit exceeded)
- `500`: Internal server error
- `503`: Service unavailable (degraded state)

### Error Codes

- `INSUFFICIENT_BALANCE`: Not enough cash for trade
- `INVALID_SYMBOL`: Symbol not supported
- `AGENT_UNAVAILABLE`: Agent not responding
- `SERVICE_DEGRADED`: Service in degraded state
- `RATE_LIMIT_EXCEEDED`: Too many requests
- `TRADE_REJECTED`: Trade rejected by risk manager
- `INVALID_STATE`: Operation not allowed in current agent state

### Structured Log Example

```json
{
  "timestamp": "2025-01-12T10:30:02.415Z",
  "level": "ERROR",
  "service": "backend",
  "component": "routes.trading.execute_trade",
  "correlation_id": "req_xyz789",
  "session_id": "sess_01HV6Z8P8ZN8TEFQH5MZ9YV24S",
  "message": "trade_rejected",
  "details": {
    "symbol": "BTCUSD",
    "reason": "INSUFFICIENT_BALANCE",
    "requested_size": 0.25,
    "available_cash": 0.21
  }
}
```

Emit entries in this format so observability tooling can pivot by `correlation_id`, `component`, or `reason` when investigating incidents.

---

## Middleware

### Authentication Middleware

- JWT token validation
- API key validation
- Role-based access control

### Rate Limiting Middleware

- Per-IP rate limiting
- Per-user rate limiting
- Configurable limits

### CORS Middleware

- Configurable allowed origins
- Credentials support
- Preflight handling

### Logging Middleware

- Request/response logging with structured format
- Correlation ID generation for request tracing
- Structured logging using structlog
- Error tracking with correlation IDs
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Startup log clearing (implemented in startup scripts or service initialization) (see [Logging Documentation](12-logging.md))
- Consistent log schema fields (`service`, `component`, `session_id`, `correlation_id`)

**Structured Logging Example**:
```python
import structlog

logger = structlog.get_logger()

# Log with context
logger.info(
    "data_update",  // Simplified format - replaces trade_executed, portfolio_update, signal_update, etc.
    trade_id="trade_123",
    symbol="BTCUSD",
    side="buy",
    quantity=0.1,
    price=50000.0,
    correlation_id="req_xyz789"
)
```

**Correlation IDs**:
- Generated for each request
- Included in all log entries related to that request
- Passed through all service calls
- Used for error tracking and debugging

**Error Handling Strategy**:
- Comprehensive try/except blocks at all integration points
- Circuit breakers prevent cascading failures
- Graceful degradation when services fail
- Detailed error messages with context
- Error correlation through request IDs
- Automatic retry with exponential backoff for transient errors

---

## Logging & Observability

The backend adheres to the centralized logging blueprint described in [Logging Documentation](12-logging.md):

- **Startup clearing**: Clear or archive previous logs during application startup (implemented in startup scripts or lifespan handler) to archive or delete stale logs and generate a new `session_id`.
- **Structured JSON schema**: Emit logs with `service="backend"`, `component`, `environment`, `session_id`, and `correlation_id` fields to maintain cross-service parity.
- **Exception capture**: Register FastAPI exception handlers that record `ERROR` entries (with stack traces redacted in production when `LOG_INCLUDE_STACKTRACE=false`).
- **Forwarding support**: When `LOG_FORWARDING_ENABLED=true`, stream logs to the configured collector while retaining STDOUT/file writes.
- **Health visibility**: Extend health checks to report logging readiness (writable directories, last rotation timestamp, forwarding status).

Refer to [Logging Documentation](12-logging.md) for rotation policy, retention strategy, and operational runbooks.

---

## Configuration

### Environment Variables

**Single Root `.env` File**: The backend reads environment variables from the **root `.env` file** in the project root directory via `ROOT_ENV_PATH` in `backend/core/config.py`. No service-specific `.env` files are needed.

**Setup**: Copy `.env.example` to `.env` in the project root and configure your values. See `.env.example` for the complete list of all available variables.

**Key Backend Variables:**

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://user:pass@localhost/trading_agent

# Redis
REDIS_URL=redis://localhost:6379

# Delta Exchange (REQUIRED)
DELTA_EXCHANGE_API_KEY=your_api_key
DELTA_EXCHANGE_API_SECRET=your_api_secret
DELTA_EXCHANGE_BASE_URL=https://api.india.delta.exchange

# Agent Communication
AGENT_COMMAND_QUEUE=agent_commands
AGENT_RESPONSE_QUEUE=agent_responses

# Feature Server
FEATURE_SERVER_URL=http://localhost:8001

# Vector Database (Optional)
QDRANT_URL=http://localhost:6333

# Security (REQUIRED)
JWT_SECRET_KEY=your_secret_key
API_KEY=your_api_key

# Telegram Alerts (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Logging
LOG_LEVEL=INFO
LOG_FORWARDING_ENABLED=false
LOG_FORWARDING_ENDPOINT=
```

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are populated, the backend automatically publishes trade notifications to the configured chat. Leaving either value blank disables the integration without requiring code changes.

### Telegram Notifications (Optional)

- Implemented via `backend.notifications.telegram.TelegramNotifier`.
- Enabled only when both credentials are present; otherwise the notifier short-circuits with an informational log entry.
- Trade executions (`POST /api/v1/trade/execute`) schedule non-blocking notifications so API latency is unaffected.
- Messages include symbol, side, size, order type, execution ID (when available), and realized PnL when supplied by the agent.
- Additional event types (risk alerts, health changes) can reuse the same notifier by injecting it into the relevant service.

Deployment checklist for Telegram alerts:

1. Create a bot with [@BotFather](https://core.telegram.org/bots#botfather) and record the token.
2. Obtain the chat ID (e.g., via @userinfobot or a simple script using `getUpdates`).
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the root `.env` file.
4. Restart the backend so the new configuration is applied.

---

## Command Operations
The project-level commands documented in the [Build Guide](11-build-guide.md#project-commands) call into backend scripts under `tools/commands/`. This section outlines the backend-specific behaviour triggered by each command.

### `start`
- Verifies connectivity to PostgreSQL and Redis before launching the backend
- Starts `uvicorn api.main:app --host 0.0.0.0 --port 8000` (auto-reload enabled in development)
- Bootstraps logging (`logs/backend/start.log`) and emits a `system.startup` event with a new `session_id`
- Registers health probes at `http://localhost:8000/api/v1/health`

### `restart`
- Gracefully stops the running `uvicorn` process via the stop routine
- Clears cached sockets/PID files under `tmp/`
- Re-sources environment variables from the root `.env` file
- Archives previous backend logs to `logs/restart/<timestamp>/backend.log`
- Invokes the `start` command to bring the service back online

### `audit`
- Executes backend unit tests (`pytest backend/tests`)
- Runs linting/formatting (`ruff check backend`, `black --check backend`)
- Validates the API by calling `GET /api/v1/health`
- Collates backend logs into `logs/audit/backend.log`
- Contributes to the consolidated report at `logs/audit/report.md`

### `error`
- Confirms the backend process is listening on port 8000
- Captures the last 200 lines from `logs/backend/backend.log`
- Highlights new `WARN`/`ERROR` entries since the previous execution
- Stores diagnostics in `logs/error/backend.log`

Use these commands to manage the backend lifecycle alongside the agent and frontend services. Additional operational guidance is provided in the [Deployment Documentation](10-deployment.md#operations--maintenance-commands).

---

## MCP Layer Integration

### Backend Integration with MCP

The backend integrates with the MCP layer through service components:

**Agent Service Integration**:
- Communicates with MCP Orchestrator for predictions
- Receives MCP Reasoning Chains from agent
- Processes MCP Model Predictions for display

**Feature Service Integration**:
- Accesses MCP Feature Server via MCP Feature Protocol
- Receives standardized `MCPFeatureResponse` objects
- Monitors feature quality scores

**Example Integration**:
```python
# backend/services/agent_service.py
class AgentService:
    def __init__(self):
        # MCP orchestrator handles all MCP protocol communication
        self.mcp_client = MCPClient()
    
    async def get_prediction(self, symbol: str):
        """Get prediction via MCP layer."""
        # Request goes through MCP Orchestrator
        result = await self.mcp_client.request_prediction(symbol)
        
        # Result contains MCP Reasoning Chain
        return {
            "reasoning_chain": result.reasoning_chain,
            "model_predictions": result.model_predictions,
            "features": result.features
        }
```

For detailed MCP layer documentation, see [MCP Layer Documentation](02-mcp-layer.md).

---

## Backend–frontend contract essentials

- **Transport**: Primary real-time path is WebSocket `GET /ws`; commands use `{ "action": "command", "command": "<name>", "request_id": "<id>", "parameters": { ... } }` with responses `{ "type": "response", "request_id", "command", "success", "data", "timestamp" }`.
- **Types**: Currency/quantity as JSON `float`; datetimes ISO 8601; backend confidence `0.0`–`1.0` (UI may show percent).
- **Signals**: `STRONG_BUY` | `BUY` | `HOLD` | `SELL` | `STRONG_SELL` (exact strings).
- **Code touchpoints** (when changing contracts): `backend/api/models/responses.py`, Pydantic request models, `frontend/services/api.ts`, `frontend/types/*`, and generated types if used.

---

## Related Documentation

- [Logging Documentation](12-logging.md) - Centralized logging architecture and operations
- [MCP Layer Documentation](02-mcp-layer.md) - MCP architecture and protocols
- [ML Models Documentation](03-ml-models.md) - Model management
- [Architecture Documentation](01-architecture.md) - System design
- [Frontend Documentation](07-frontend.md) - Frontend implementation
- [Deployment Documentation](10-deployment.md) - Setup and deployment
- [Build Guide](11-build-guide.md) - Build instructions
- [Project Rules](14-project-rules.md) - Coding standards

