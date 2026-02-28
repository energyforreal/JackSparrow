# Backend-Frontend API Integration Contract

## Overview

This document defines the complete WebSocket-based API contract between the backend and frontend, ensuring type safety, consistency, and reliability of data exchange.

**Document Version:** 2.0 (WebSocket-Only)  
**Last Updated:** 2026-02-01  
**Status:** Active  
**Architecture:** WebSocket-Only Communication

## Table of Contents

1. [Data Types & Serialization](#data-types--serialization)
2. [WebSocket Commands](#websocket-commands)
3. [WebSocket Real-Time Channels](#websocket-real-time-channels)
4. [Error Handling](#error-handling)
5. [Examples](#examples)
6. [Migration from REST API](#migration-from-rest-api)

## Data Types & Serialization

### Core Types

All numeric financial values use the following conventions:

| Type | Backend | JSON (WebSocket) | Frontend |
|------|---------|-----------------|----------|
| Currency/Price | `Decimal` | `float` | `number` |
| Quantity | `Decimal` | `float` | `number` |
| Confidence | `float (0.0-1.0)` | `float` | `number (0-100 after normalization)` |
| Date/Time | `datetime` | ISO 8601 string | `Date` object |

### Serialization Rules

**Important:** All Decimal fields are serialized as `float` in JSON for WebSocket communication.

```typescript
// ✓ CORRECT: Backend returns Decimal as float
{
  "total_value": 10000.0,
  "available_balance": 9500.5,
  "unrealized_pnl": 150.25
}

// ✗ WRONG: Backend should NOT return Decimal as string
{
  "total_value": "10000.00",
  "available_balance": "9500.50"
}
```

### Signal Type Enumeration

The trading signal type must be one of these exact values:

```typescript
type SignalType = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'
```

WebSocket commands and real-time updates use the same signal type values.

### Confidence Score Normalization

- **Backend**: Always returns `0.0 - 1.0` range
- **Frontend**: Converts to `0 - 100` range for display using `normalizeConfidenceToPercent()`

```typescript
// Backend
{
  "confidence": 0.85  // 85% confidence
}

// Frontend (after normalization)
normalizeConfidenceToPercent(0.85) === 85
```

## WebSocket Commands

All API operations use WebSocket commands with a request/response pattern. Commands are sent via the main WebSocket connection and responses are received on the same connection.

### Command Format

**Request:**
```typescript
{
  action: "command",
  command: string,  // Command name
  request_id: string,  // Unique request ID for correlation
  parameters?: Record<string, unknown>  // Command-specific parameters
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: string,  // Matches request ID
  command: string,  // Command name
  success: boolean,  // Whether command succeeded
  data?: unknown,  // Response data (if success)
  error?: string,  // Error message (if failed)
  timestamp: string  // ISO 8601 timestamp
}
```

### Health Command

**Command:** `get_health`

**Request:**
```typescript
{
  action: "command",
  command: "get_health",
  request_id: "req_123",
  parameters: {}
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_123",
  command: "get_health",
  success: true,
  data: {
    status: "healthy" | "degraded" | "unhealthy",
    health_score: 0.95,  // 0.0-1.0
    services: {
      [service_name]: {
        status: "up" | "down" | "degraded",
        latency_ms?: 2.1,
        error?: "Connection failed",
        details?: { version: "1.2.3" }
      }
    },
    agent_state: "MONITORING",
    degradation_reasons: [],
    timestamp: "2026-02-01T10:30:00Z"
  }
}
```

**Example:**
```json
{
  "status": "healthy",
  "health_score": 0.95,
  "services": {
    "database": { "status": "up", "latency_ms": 2.1 },
    "redis": { "status": "up", "latency_ms": 1.5 },
    "agent": { "status": "up", "latency_ms": 45.2 }
  },
  "agent_state": "MONITORING",
  "degradation_reasons": [],
  "timestamp": "2026-02-01T12:00:00Z"
}
```

### Prediction Command

**Command:** `predict`

**Request:**
```typescript
{
  action: "command",
  command: "predict",
  request_id: "req_456",
  parameters: {
    symbol: "BTCUSD",
    context?: {
      interval: "15m",
      features: {}
    }
  }
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_456",
  command: "predict",
  success: true,
  data: {
    signal: "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
    confidence: 0.85,  // 0.0-1.0
    position_size: 0.02,
    reasoning_chain: {
      chain_id: "chain_123",
      timestamp: "2026-02-01T10:30:00Z",
      steps: [
        {
          step_number: 1,
          step_name: "Market Analysis",
          description: "Bullish trend detected",
          confidence: 0.8,
          evidence: ["RSI below 30", "Volume increasing"]
        }
      ],
      conclusion: "Strong buy signal",
      final_confidence: 0.85
    },
    model_predictions: [
      {
        model_name: "xgboost_v1",
        prediction: 0.9,
        confidence: 0.82,
        reasoning: "Technical indicators bullish"
      }
    ],
    model_consensus: [
      {
        model_name: "xgboost_v1",
        signal: "BUY",
        confidence: 0.82
      }
    ],
    individual_model_reasoning: [
      {
        model_name: "xgboost_v1",
        reasoning: "Strong technical setup",
        confidence: 0.82
      }
    ],
    market_context: {
      symbol: "BTCUSD",
      price: 45000.0,
      volume_24h: 1250000
    },
    timestamp: "2026-02-01T10:30:00Z"
  }
}
```

### Portfolio Commands

#### Get Portfolio Summary

**Command:** `get_portfolio`

**Request:**
```typescript
{
  action: "command",
  command: "get_portfolio",
  request_id: "req_789",
  parameters: {}
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_789",
  command: "get_portfolio",
  success: true,
  data: {
    total_value: 10500.50,
    available_balance: 9500.00,
    open_positions: 2,
    total_unrealized_pnl: 150.25,
    total_realized_pnl: 200.00,
    positions: [
      {
        id: "pos_123",
        symbol: "BTCUSD",
        side: "buy",
        quantity: 0.05,
        entry_price: 44000.0,
        current_price: 45000.0,
        unrealized_pnl: 250.0,
        opened_at: "2026-01-30T09:00:00Z",
        status: "OPEN"
      }
    ],
    timestamp: "2026-02-01T10:30:00Z"
  }
}
```

#### Get Positions

**Command:** `get_positions`

**Request:**
```typescript
{
  action: "command",
  command: "get_positions",
  request_id: "req_101",
  parameters: {
    symbol?: "BTCUSD",  // Optional filter
    status?: "OPEN",    // Optional filter
    limit?: 100,        // Optional limit
    offset?: 0          // Optional offset
  }
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_101",
  command: "get_positions",
  success: true,
  data: [
    {
      id: "pos_123",
      symbol: "BTCUSD",
      side: "buy",
      quantity: 0.05,
      entry_price: 44000.0,
      current_price: 45000.0,
      unrealized_pnl: 250.0,
      opened_at: "2026-01-30T09:00:00Z",
      status: "OPEN"
    }
  ]
}
```

```typescript
{
  position_id: string,
  symbol: string,
  side: "LONG" | "SHORT",
  quantity: number,
  entry_price: number,
  current_price?: number,
  unrealized_pnl?: number,
  status: "OPEN" | "CLOSED" | "LIQUIDATED",
  opened_at: string,  // ISO 8601
  stop_loss?: number,
  take_profit?: number
}
```

#### Get Trades

**Command:** `get_trades`

**Request:**
```typescript
{
  action: "command",
  command: "get_trades",
  request_id: "req_202",
  parameters: {
    symbol?: "BTCUSD",     // Optional filter
    status?: "EXECUTED",   // Optional filter
    limit?: 100,           // Optional limit
    offset?: 0             // Optional offset
  }
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_202",
  command: "get_trades",
  success: true,
  data: [
    {
      trade_id: "trade_456",
      symbol: "BTCUSD",
      side: "BUY",
      quantity: 0.05,
      price: 44000.0,
      status: "EXECUTED",
      executed_at: "2026-01-30T09:15:00Z",
      reasoning_chain_id: "chain_123"
    }
  ]
}
```

### Trade Execution Command

**Command:** `execute_trade`

**Request:**
```typescript
{
  action: "command",
  command: "execute_trade",
  request_id: "req_303",
  parameters: {
    symbol: "BTCUSD",
    side: "buy",
    quantity: 0.05,
    order_type: "MARKET",
    price: null,        // For MARKET orders
    stop_loss: 43000,   // Optional
    take_profit: 46000  // Optional
  }
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_303",
  command: "execute_trade",
  success: true,
  data: {
    order_id: "order_789",
    status: "EXECUTED",
    executed_price: 45000.0,
    executed_quantity: 0.05,
    timestamp: "2026-02-01T10:35:00Z"
  }
}
```
}
```

### Market Data Endpoints

#### Get Market Data

```http
GET /api/v1/market/data?symbol=BTCUSD&interval=1h&limit=100
```

**Response:** `MarketDataResponse`

```typescript
{
  symbol: string,
  interval: string,
  candles: Array<{
    timestamp: string,
    open: number,
    high: number,
    low: number,
    close: number,
    volume: number
  }>,
  latest_price: number,
  timestamp: string
}
```

#### Get Agent Status

**Command:** `get_agent_status`

**Request:**
```typescript
{
  action: "command",
  command: "get_agent_status",
  request_id: "req_404",
  parameters: {}
}
```

**Response:**
```typescript
{
  type: "response",
  request_id: "req_404",
  command: "get_agent_status",
  success: true,
  data: {
    available: true,
    state: "MONITORING",
    last_update: "2026-02-01T10:30:00Z",
    active_symbols: ["BTCUSD", "ETHUSD"],
    model_count: 5,
    health_status: "healthy",
    message: "All systems operational",
    latency_ms: 45.2
  }
}
```

## WebSocket Real-Time Channels

### Connection & Subscription

**Connect to:** `ws://localhost:8000/ws` (or `wss://api.example.com/ws` in production)

**Real-Time Subscription Channels:**

Subscribe to real-time updates using 3 core channels:

```typescript
{
  "action": "subscribe",
  "channels": [
    "data_update",      // Trading signals, portfolio updates, trade executions, market data
    "agent_update",     // Agent state changes
    "system_update"     // Health updates, time sync, performance metrics
  ]
}
```

### Real-Time Message Format

Real-time updates use a unified envelope format:

```typescript
{
  type: "data_update" | "agent_update" | "system_update" | "response" | "error",
  resource?: "signal" | "portfolio" | "trade" | "market" | "performance" | "health" | "time" | "agent" | "model",
  data?: any,
  timestamp: string,  // ISO 8601
  sequence?: number,
  source: string,
  request_id?: string,
  server_timestamp_ms?: number
}
```

### Message Types

#### data_update (Unified Data Updates)

Replaces: `signal_update`, `portfolio_update`, `trade_executed`, `market_tick`, `reasoning_chain_update`, `model_prediction_update`

**Signal Update:**
```typescript
{
  type: "data_update",
  resource: "signal",
  data: {
    signal: SignalType,
    confidence: number,  // 0.0-1.0
    position_size?: number,
    reasoning_chain: ReasoningChain,
    model_predictions: ModelPrediction[],
    model_consensus: ModelConsensusEntry[],
    individual_model_reasoning: ModelReasoningEntry[],
    timestamp: string
  },
  timestamp: string,
  source: "agent"
}
```

**Portfolio Update:**
```typescript
{
  type: "data_update",
  resource: "portfolio",
  data: {
    total_value: number,
    available_balance: number,
    open_positions: number,
    total_unrealized_pnl: number,
    total_realized_pnl: number,
    positions: PositionResponse[],
    timestamp: string
  },
  timestamp: string,
  source: "system"
}
```

**Trade Update:**
```typescript
{
  type: "data_update",
  resource: "trade",
  data: {
    trade_id: string,
    position_id?: string,
    symbol: string,
    side: "BUY" | "SELL",
    quantity: number,
    price: number,
    timestamp: string
  },
  timestamp: string,
  source: "system"
}
```

**Market Update:**
```typescript
{
  type: "data_update",
  resource: "market",
  data: {
    symbol: string,
    price: number,
    volume?: number,
    timestamp: string,
    change_24h_pct?: number,
    high_24h?: number,
    low_24h?: number
  },
  timestamp: string,
  source: "system"
}
```

**Model Update:**
```typescript
{
  type: "data_update",
  resource: "model",
  data: {
    symbol: string,
    consensus_signal: number,
    consensus_confidence: number,  // 0.0-1.0
    individual_model_reasoning: ModelReasoningEntry[],
    model_consensus: ModelConsensusEntry[],
    model_predictions: ModelPrediction[],
    timestamp: string
  },
  timestamp: string,
  source: "agent"
}
```

#### agent_update (Agent State Changes)

Replaces: `agent_state`

```typescript
{
  type: "agent_update",
  resource: "agent",
  data: {
    state: string,
    timestamp?: string,
    reason?: string
  },
  timestamp: string,
  source: "agent"
}
```

#### system_update (System Updates)

Replaces: `health_update`, `time_sync`, `performance_update`

**Health Update:**
```typescript
{
  type: "system_update",
  resource: "health",
  data: {
    status: "healthy" | "degraded" | "unhealthy",
    health_score: number,  // 0.0-1.0
    services: Record<string, HealthServiceStatus>,
    agent_state?: string,
    degradation_reasons: string[],
    timestamp: string
  },
  timestamp: string,
  source: "system"
}
```

**Time Sync:**
```typescript
{
  type: "system_update",
  resource: "time",
  data: {
    server_time: string,  // ISO 8601
    timestamp_ms: number
  },
  timestamp: string,
  source: "system"
}
```

### Backward Compatibility

The frontend automatically normalizes legacy message types to the new format. Legacy types (`signal_update`, `portfolio_update`, etc.) are still supported during the transition period.

#### Legacy Message Types (Deprecated)

Detailed reasoning steps received.

```typescript
{
  type: "reasoning_chain_update",
  data: {
    reasoning_chain: ReasoningStep[],
    conclusion: string,
    final_confidence: number,
    chain_id: string,
    timestamp: string
  }
}
```

#### model_prediction_update

Individual model predictions updated.

```typescript
{
  type: "model_prediction_update",
  data: {
    consensus_signal?: number,
    consensus_confidence?: number,
    individual_model_reasoning: ModelReasoningEntry[],
    model_consensus: ModelConsensusEntry[],
    model_predictions: ModelPrediction[],
    timestamp: string
  }
}
```

## Error Handling

### HTTP Error Response Format

```typescript
{
  error: {
    code: string,
    message: string,
    details?: Record<string, unknown>,
    request_id?: string
  }
}
```

**Example:**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid trading symbol",
    "details": {
      "symbol": "INVALID",
      "valid_symbols": ["BTCUSD", "ETHUSD"]
    },
    "request_id": "req-12345"
  }
}
```

### Common Error Codes

| Code | Status | Meaning |
|------|--------|---------|
| `VALIDATION_ERROR` | 400 | Invalid request parameters |
| `AUTHENTICATION_REQUIRED` | 401 | Missing or invalid API key |
| `INSUFFICIENT_BALANCE` | 403 | Not enough balance for trade |
| `SYMBOL_NOT_FOUND` | 404 | Trading symbol not found |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |

### Retry Strategy

The frontend should implement exponential backoff retry logic:

- Retry on: 5xx errors, timeouts, network errors
- Don't retry on: 4xx errors (client errors)
- Max retries: 3
- Backoff: `delay = base_delay * 2^attempt` (capped at 10s)

## Migration from REST API

### Important Changes

**Version 2.0** introduces a WebSocket-only architecture. All REST API endpoints have been deprecated in favor of WebSocket commands.

### Migration Guide

| Legacy REST API | New WebSocket Command | Notes |
|-----------------|----------------------|-------|
| `GET /api/v1/health` | `get_health` command | Real-time health via `system_update` channel |
| `POST /api/v1/predict` | `predict` command | Real-time signals via `data_update` channel |
| `POST /api/v1/trade/execute` | `execute_trade` command | Real-time executions via `data_update` channel |
| `GET /api/v1/portfolio/summary` | `get_portfolio` command | Real-time portfolio via `data_update` channel |
| `GET /api/v1/portfolio/positions` | `get_positions` command | N/A |
| `GET /api/v1/portfolio/trades` | `get_trades` command | N/A |
| `GET /api/v1/admin/agent/status` | `get_agent_status` command | Real-time agent state via `agent_update` channel |

### Breaking Changes

1. **No more HTTP requests** - All API operations now use WebSocket
2. **Request/Response pattern** - Commands use `request_id` for correlation
3. **Real-time subscriptions** - Data updates are pushed automatically
4. **No authentication headers** - Authentication handled at WebSocket connection level

### Migration Steps

1. **Replace REST calls with WebSocket commands:**
   ```typescript
   // Old: fetch('/api/v1/predict', { method: 'POST', body: JSON.stringify({ symbol }) })
   // New: ws.send(JSON.stringify({ action: 'command', command: 'predict', request_id: 'req_123', parameters: { symbol } }))
   ```

2. **Subscribe to real-time updates:**
   ```typescript
   ws.send(JSON.stringify({
     action: 'subscribe',
     channels: ['data_update', 'agent_update', 'system_update']
   }));
   ```

3. **Handle responses asynchronously:**
   ```typescript
   ws.onmessage = (event) => {
     const message = JSON.parse(event.data);
     if (message.type === 'response' && message.request_id === 'req_123') {
       // Handle response to your command
     }
   };
   ```

## Examples

### Complete Request/Response Flow

**1. Get initial predictions:**

```bash
curl -X POST http://localhost:8000/api/v1/predict \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"symbol": "BTCUSD"}'
```

**Response:**

```json
{
  "signal": "BUY",
  "confidence": 0.85,
  "position_size": 0.05,
  "reasoning_chain": {
    "chain_id": "chain_abc123",
    "timestamp": "2026-02-01T12:00:00Z",
    "steps": [
      {
        "step_number": 1,
        "step_name": "Market Analysis",
        "description": "Analyzing current market conditions",
        "evidence": ["RSI shows oversold", "MACD bullish crossover"],
        "confidence": 0.82,
        "data_freshness_seconds": 2
      }
    ],
    "conclusion": "Strong buy signal based on technical indicators",
    "final_confidence": 0.85
  },
  "model_predictions": [
    {
      "model_name": "xgboost_BTCUSD_15m",
      "prediction": 0.75,
      "confidence": 0.88,
      "reasoning": "Strong bullish indicators"
    }
  ],
  "model_consensus": [
    {
      "model_name": "xgboost_BTCUSD_15m",
      "signal": "BUY",
      "confidence": 0.88
    }
  ],
  "individual_model_reasoning": [],
  "timestamp": "2026-02-01T12:00:00Z"
}
```

**2. Connect to WebSocket and subscribe:**

```typescript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  ws.send(JSON.stringify({
    action: 'subscribe',
    channels: ['signal_update', 'portfolio_update', 'market_tick']
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);
};
```

**3. Receive WebSocket updates:**

```json
{
  "type": "signal_update",
  "data": {
    "signal": "STRONG_BUY",
    "confidence": 0.92,
    "reasoning_chain": { ... }
  }
}
```

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-02-01 | **BREAKING**: WebSocket-only architecture. REST API deprecated. |
| 1.0 | 2026-02-01 | Initial release with Decimal standardization and confidence normalization |

## Support & Questions

For issues or clarifications about this API contract, please refer to:
- Backend implementation: `backend/api/models/responses.py`
- Frontend types: `frontend/schemas/api.validation.ts`
- Integration tests: `tests/functionality/`
