# WebSocket Communication Simplification

## Overview

The WebSocket communication layer between frontend and backend has been simplified to reduce complexity and improve maintainability.

**Date:** 2026-02-01  
**Status:** ✅ Completed

## Changes Summary

### Before Simplification

- **10+ WebSocket message types**: `signal_update`, `portfolio_update`, `trade_executed`, `market_tick`, `agent_state`, `health_update`, `time_sync`, `reasoning_chain_update`, `model_prediction_update`, `performance_update`
- **8 subscription channels**: One channel per message type
- **Complex message handling**: Multiple switch statements across different hooks
- **Mixed message formats**: Inconsistent structure across message types

### After Simplification

- **3 core WebSocket message types**: `data_update`, `agent_update`, `system_update`
- **3 subscription channels**: Simplified channel structure
- **Unified message format**: Consistent envelope format with `resource` field
- **Backward compatible**: Legacy message types automatically normalized

## Implementation Details

### Unified Message Envelope Format

All WebSocket messages now use a standardized envelope format:

```typescript
interface WebSocketEnvelope {
  type: "data_update" | "agent_update" | "system_update" | "response" | "error"
  resource?: "signal" | "portfolio" | "trade" | "market" | "performance" | "health" | "time" | "agent" | "model"
  data?: any
  timestamp: string  // ISO 8601
  sequence?: number
  source: string
  request_id?: string
  server_timestamp_ms?: number
}
```

### Message Type Mapping

| New Format | Resource | Replaces Legacy Types |
|------------|----------|---------------------|
| `data_update` | `signal` | `signal_update`, `reasoning_chain_update` |
| `data_update` | `portfolio` | `portfolio_update` |
| `data_update` | `trade` | `trade_executed` |
| `data_update` | `market` | `market_tick` |
| `data_update` | `model` | `model_prediction_update` |
| `agent_update` | `agent` | `agent_state` |
| `system_update` | `health` | `health_update` |
| `system_update` | `time` | `time_sync` |
| `system_update` | `performance` | `performance_update` |

### Subscription Channels

**Before:**
```typescript
channels: [
  'agent_state',
  'signal_update',
  'reasoning_chain_update',
  'model_prediction_update',
  'market_tick',
  'trade_executed',
  'portfolio_update',
  'health_update'
]
```

**After:**
```typescript
channels: [
  'data_update',      // Unified data updates
  'agent_update',     // Agent state changes
  'system_update'     // System updates (health, time, etc.)
]
```

## Backend Changes

### Files Modified

1. **`backend/services/agent_event_subscriber.py`**
   - Updated all broadcasts to use simplified message builders
   - Replaced legacy `portfolio_update` broadcasts with `create_portfolio_update()`
   - Replaced legacy `reasoning_chain_update` broadcasts with `create_signal_update()`
   - All broadcasts now use `WebSocketEnvelope` format

2. **`backend/core/websocket_messages.py`**
   - Already had simplified message builders (no changes needed)
   - Provides `create_signal_update()`, `create_portfolio_update()`, etc.

3. **`backend/api/websocket/manager.py`**
   - Already supports both `Dict` and `WebSocketEnvelope` formats (no changes needed)

### Backend Message Builders

```python
from backend.core.websocket_messages import (
    create_signal_update,
    create_portfolio_update,
    create_trade_update,
    create_market_update,
    create_agent_state_update,
    create_model_update,
    create_health_update,
    create_time_sync
)

# Example usage
signal_message = create_signal_update(signal_data)
await websocket_manager.broadcast(signal_message, channel="data_update")
```

## Frontend Changes

### Files Modified

1. **`frontend/hooks/useWebSocket.ts`**
   - Added `normalizeWebSocketMessage()` function for backward compatibility
   - Updated subscription channels to 3 core channels
   - Handles both new and legacy message formats

2. **`frontend/hooks/useTradingData.ts`**
   - Fixed state mutation bug (`state.dataSource = 'api'` → dispatch action)
   - Updated reducer to handle simplified message format
   - Added backward compatibility for legacy message types
   - Improved message handling logic

3. **`frontend/schemas/api.validation.ts`**
   - Added `SimplifiedWebSocketEnvelopeSchema`
   - Updated `WebSocketMessageSchema` to support both formats
   - Maintains backward compatibility

### Frontend Message Normalization

The frontend automatically normalizes legacy message types:

```typescript
function normalizeWebSocketMessage(message: any): WebSocketMessage {
  // New format already has type and resource
  if (message.type && ['data_update', 'agent_update', 'system_update'].includes(message.type)) {
    return message
  }
  
  // Legacy format - convert to simplified format
  if (message.type === 'signal_update') {
    return { ...message, type: 'data_update', resource: 'signal' }
  }
  // ... other legacy type mappings
}
```

## Benefits

### 1. Reduced Complexity
- **70% reduction** in message types (10+ → 3)
- **62% reduction** in subscription channels (8 → 3)
- Simpler message routing logic

### 2. Improved Maintainability
- Single unified format to maintain
- Easier to add new resource types
- Consistent message structure

### 3. Better Type Safety
- Unified TypeScript interfaces
- Consistent validation schemas
- Reduced potential for type errors

### 4. Backward Compatibility
- Legacy messages automatically normalized
- No breaking changes for existing clients
- Smooth transition period

### 5. Performance
- Fewer subscriptions to manage
- Simpler message routing
- Reduced overhead

## Migration Guide

### For Frontend Developers

No changes required! The frontend automatically handles both formats. However, you can update code to use the new format:

**Old:**
```typescript
if (message.type === 'signal_update') {
  // handle signal
}
```

**New:**
```typescript
if (message.type === 'data_update' && message.resource === 'signal') {
  // handle signal
}
```

### For Backend Developers

Always use the simplified message builders:

**Old:**
```python
await websocket_manager.broadcast({
    "type": "portfolio_update",
    "data": portfolio_data
}, channel="portfolio")
```

**New:**
```python
portfolio_message = create_portfolio_update(portfolio_data)
await websocket_manager.broadcast(portfolio_message, channel="data_update")
```

## Testing

### Verification Checklist

- [x] Backend broadcasts use simplified format
- [x] Frontend handles simplified format
- [x] Frontend handles legacy format (backward compatibility)
- [x] All message types properly normalized
- [x] Subscription channels simplified
- [x] Validation schemas updated
- [x] No breaking changes

### Test Cases

1. **New Format Messages**: Verify all resource types work correctly
2. **Legacy Format Messages**: Verify automatic normalization
3. **Subscription**: Verify 3-channel subscription works
4. **State Updates**: Verify all data updates correctly
5. **Error Handling**: Verify error messages use simplified format

## Related Documentation

- [API Contract](./API_CONTRACT.md) - Complete API documentation
- [Frontend Documentation](./07-frontend.md) - Frontend implementation details
- [Integration Quick Reference](./INTEGRATION_QUICK_REFERENCE.md) - Quick reference guide

## WebSocket Command Architecture (2026-02-01)

### Overview

Building on the simplified message format, the system now uses **WebSocket-only communication** with both real-time updates and request/response commands over the same WebSocket connection.

### Command Pattern

**Request Format:**
```typescript
{
  action: "command",
  command: string,        // Command name (predict, execute_trade, get_portfolio, etc.)
  request_id: string,     // Unique correlation ID
  parameters?: object     // Command-specific parameters
}
```

**Response Format:**
```typescript
{
  type: "response",
  request_id: string,     // Matches request ID
  command: string,        // Command name
  success: boolean,       // Success flag
  data?: any,            // Response data
  error?: string,        // Error message if failed
  timestamp: string      // Response timestamp
}
```

### Available Commands

| Command | Purpose | Replaces REST API |
|---------|---------|-------------------|
| `get_health` | System health check | `GET /api/v1/health` |
| `predict` | AI prediction request | `POST /api/v1/predict` |
| `execute_trade` | Trade execution | `POST /api/v1/trade/execute` |
| `get_portfolio` | Portfolio summary | `GET /api/v1/portfolio/summary` |
| `get_positions` | Position list | `GET /api/v1/portfolio/positions` |
| `get_trades` | Trade history | `GET /api/v1/portfolio/trades` |
| `get_agent_status` | Agent status | `GET /api/v1/admin/agent/status` |

### Example Command Flow

```typescript
// 1. Send command
websocket.send(JSON.stringify({
  action: "command",
  command: "predict",
  request_id: "req_123",
  parameters: { symbol: "BTCUSD" }
}));

// 2. Receive response
websocket.onmessage = (event) => {
  const response = JSON.parse(event.data);
  if (response.type === "response" && response.request_id === "req_123") {
    if (response.success) {
      console.log("Prediction:", response.data);
    } else {
      console.error("Error:", response.error);
    }
  }
};
```

### Communication Logging

All WebSocket communication is now logged with correlation IDs for complete traceability:

```json
{
  "timestamp": "2026-02-01T10:30:00Z",
  "service": "backend",
  "direction": "outbound",
  "protocol": "websocket",
  "message_type": "response",
  "resource": "predict",
  "correlation_id": "req_123",
  "latency_ms": 45.2,
  "payload_summary": {
    "size_bytes": 1024,
    "payload": {"signal": "BUY", "confidence": 0.85}
  }
}
```

## Future Improvements

1. **Message Compression**: Consider compression for high-frequency command usage
2. **Command Batching**: Support batching multiple commands in single request
3. **Command Timeouts**: Configurable timeouts per command type
4. **Command Retry Logic**: Automatic retry for failed commands
5. **Remove REST API**: Complete removal of deprecated REST endpoints

## Conclusion

The WebSocket communication system now provides a complete, unified API using both real-time updates and request/response commands over a single WebSocket connection. This eliminates protocol complexity while providing comprehensive logging and correlation tracking for all inter-service communication.
