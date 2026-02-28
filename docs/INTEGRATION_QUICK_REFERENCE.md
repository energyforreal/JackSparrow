# Backend-Frontend Integration Quick Reference

## Key Files

### Documentation
- **API Contract:** `docs/API_CONTRACT.md` - Complete API specification
- **Integration Summary:** `docs/INTEGRATION_IMPROVEMENTS_SUMMARY.md` - Implementation details
- **This File:** `docs/INTEGRATION_QUICK_REFERENCE.md` - Quick lookup guide

### Backend
- **Response Models:** `backend/api/models/responses.py` - All API response types with Decimal serialization
- **Enums:** `backend/core/enums.py` - Signal types and status enumerations
- **Event Subscriber:** `backend/services/agent_event_subscriber.py` - WebSocket event handling
- **WebSocket Manager:** `backend/api/websocket/manager.py` - Real-time broadcast management

### Frontend
- **Validation Schemas:** `frontend/schemas/api.validation.ts` - Zod runtime validation
- **Type Enums:** `frontend/types/enums.ts` - Frontend enumeration definitions
- **API Client:** `frontend/services/api.ts` - HTTP client with retry logic
- **Hooks:** `frontend/hooks/useAgent.ts`, `frontend/hooks/useWebSocket.ts` - Data fetching
- **Formatters:** `frontend/utils/formatters.ts` - Data normalization utilities

### Scripts
- **Type Generator:** `scripts/generate_api_types.py` - OpenAPI → TypeScript generator

## Data Type Reference

### Financial Values (Decimal → float)
```typescript
// Backend Pydantic
quantity: Decimal = Field(..., example=0.1)

// JSON Response (HTTP/WebSocket)
{ "quantity": 0.1 }  // float, NOT string

// Frontend
const qty: number = 0.1;
```

### Confidence Scores (0.0 to 1.0)
```typescript
// Backend
confidence: float  // Always 0.0-1.0

// Frontend Display
const percentage = normalizeConfidenceToPercent(0.85);  // Returns 85
```

### Timestamps (ISO 8601)
```typescript
// Backend
timestamp: datetime = Field(..., example="2026-02-01T12:00:00Z")

// JSON Response
{ "timestamp": "2026-02-01T12:00:00Z" }

// Frontend (parsed to Date)
const date = normalizeDate("2026-02-01T12:00:00Z");
```

## Signal Types

### Valid Values
```
STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL
```

### Backend Validation
```python
from backend.core.enums import SignalType

# Validate
if SignalType.is_valid(signal):
    pass

# Normalize (defaults to HOLD if invalid)
normalized = SignalType.normalize(signal)
```

### Frontend Validation
```typescript
import { isValidSignal, normalizeSignalType } from '@/types/enums';

// Validate
if (isValidSignal(signal)) {
  const label = getSignalLabel(signal);  // "Strong Buy", "Buy", etc.
  const color = getSignalColor(signal);   // UI color codes
}
```

## Position & Trade Status

### Position Status
```
OPEN | CLOSED | LIQUIDATED
```

### Trade Status
```
EXECUTED | PENDING | FAILED
```

### Trade Side
```
BUY | SELL
```

### Position Side
```
LONG | SHORT
```

## WebSocket Message Types

### Simplified Format (Current)

The WebSocket communication has been simplified to 3 core message types:

| Message Type | Resource | Replaces | Sent When |
|-------------|----------|----------|-----------|
| `data_update` | `signal` | `signal_update`, `reasoning_chain_update` | New trading signal |
| `data_update` | `portfolio` | `portfolio_update` | Portfolio changed |
| `data_update` | `trade` | `trade_executed` | Trade completed |
| `data_update` | `market` | `market_tick` | Price updated |
| `data_update` | `model` | `model_prediction_update` | Model predictions |
| `agent_update` | `agent` | `agent_state` | Agent status changed |
| `system_update` | `health` | `health_update` | Health changed (60s) |
| `system_update` | `time` | `time_sync` | Periodic sync (30s) |
| `system_update` | `performance` | `performance_update` | Performance data |

### Message Format

All messages use unified envelope format:

```typescript
{
  type: "data_update" | "agent_update" | "system_update",
  resource: "signal" | "portfolio" | "trade" | "market" | "model" | "agent" | "health" | "time" | "performance",
  data: any,  // Resource-specific data
  timestamp: string,
  source: string
}
```

### Connect & Subscribe

```typescript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  ws.send(JSON.stringify({
    action: 'subscribe',
    channels: ['data_update', 'agent_update', 'system_update']
  }));
};
```

### Legacy Format (Backward Compatible)

The frontend automatically handles legacy message types for backward compatibility. Legacy types are deprecated but still supported.

## API Endpoints Quick Reference

### Health
```
GET /api/v1/health
→ HealthResponse
```

### Predictions
```
POST /api/v1/predict
Body: { symbol: "BTCUSD" }
→ PredictResponse
```

### Portfolio
```
GET /api/v1/portfolio/summary → PortfolioSummaryResponse
GET /api/v1/portfolio/positions → PositionResponse[]
GET /api/v1/portfolio/trades → TradeResponse[]
GET /api/v1/portfolio/performance?days=30 → Performance metrics
```

### Market Data
```
GET /api/v1/market/data?symbol=BTCUSD&interval=1h → MarketDataResponse
GET /api/v1/market/ticker?symbol=BTCUSD → Ticker data
```

### Admin
```
GET /api/v1/admin/agent/status → AgentStatusResponse
POST /api/v1/admin/agent/control → Control result
```

## Error Handling

### HTTP Error Response
```typescript
{
  error: {
    code: string,        // Error code like "VALIDATION_ERROR"
    message: string,     // User-friendly message
    details?: object,    // Additional details
    request_id?: string  // For debugging
  }
}
```

### Common Error Codes
| Code | Status | Meaning |
|------|--------|---------|
| VALIDATION_ERROR | 400 | Invalid request |
| AUTHENTICATION_REQUIRED | 401 | Missing API key |
| INSUFFICIENT_BALANCE | 403 | Not enough balance |
| SYMBOL_NOT_FOUND | 404 | Symbol doesn't exist |
| RATE_LIMITED | 429 | Too many requests |
| INTERNAL_ERROR | 500 | Server error |

### Retry Strategy
- **Retry on:** 5xx errors, timeouts, network errors
- **Don't retry on:** 4xx errors (client errors)
- **Max retries:** 3
- **Backoff:** exponential, capped at 10s

## Frontend Data Flow

```
Backend API/WebSocket
         ↓
useWebSocket Hook (connection & messages)
         ↓
useAgent Hook (data aggregation)
         ↓
Component Hooks (portfolio, predictions, etc.)
         ↓
UI Components (Dashboard, Cards, etc.)
```

### Data Priority
1. **WebSocket updates** (highest - real-time)
2. **Initial API fetch** (medium - startup)
3. **Polling fallback** (lowest - if disconnected)

## Type Validation

### Runtime Validation with Zod

```typescript
import { validateResponse, PredictResponseSchema } from '@/schemas/api.validation';

const raw = await apiClient.getPrediction();
const validated = validateResponse(raw, PredictResponseSchema, 'Prediction');

if (validated) {
  // Type narrowed to PredictResponse
  console.log(validated.signal);  // ✓ TypeScript knows this exists
  console.log(validated.confidence);  // ✓ Type: number
}
```

## Configuration

### Environment Variables

**Backend:**
```bash
# .env or environment
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://...
API_KEY=your-api-key
```

**Frontend:**
```bash
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_BACKEND_API_KEY=your-api-key
```

## Common Tasks

### Generate TypeScript Types from OpenAPI
```bash
python scripts/generate_api_types.py --api-url http://localhost:8000
# Output: frontend/types/api.generated.ts
```

### Validate API Response at Runtime
```typescript
import { validateResponse, HealthResponseSchema } from '@/schemas/api.validation';

const health = await apiClient.getHealth();
const validated = validateResponse(health, HealthResponseSchema, 'Health');
if (!validated) {
  // Handle validation failure
  console.error('Invalid health response');
}
```

### Map Confidence to Signal
```python
from backend.core.enums import get_signal_from_confidence

# Confidence 0.85 → "STRONG_BUY"
signal = get_signal_from_confidence(0.85)
```

### Get Signal Display Info
```typescript
import { getSignalLabel, getSignalColor } from '@/types/enums';

const label = getSignalLabel('STRONG_BUY');  // "Strong Buy"
const color = getSignalColor('STRONG_BUY');  // "#00c853"
```

## Performance Tips

1. **Caching Durations:**
   - Health: 30 seconds
   - Portfolio: 5 seconds
   - Market data: 1-300 seconds (interval dependent)

2. **Reduce WebSocket Message Volume:**
   - Subscribe only to needed channels
   - Use selective subscriptions

3. **Batch Updates:**
   - Frontend combines multiple sources into single state update
   - Avoids excessive re-renders

4. **Connection Optimization:**
   - WebSocket maintains single persistent connection
   - Reduces connection overhead vs. polling

## Troubleshooting

### WebSocket Not Connecting
1. Check `NEXT_PUBLIC_WS_URL` is set correctly
2. Verify backend is running on expected port
3. Check CORS settings in backend
4. Look for errors in browser console

### Type Validation Failures
1. Check response structure matches schema
2. Verify all required fields are present
3. Check data types (confidence should be 0.0-1.0)
4. Enable debug logging to see validation errors

### Confidence Score Issues
1. Backend should send 0.0-1.0 range
2. Frontend normalizeConfidenceToPercent handles conversion
3. If receiving 0-100 range, check backend code

### Signal Type Errors
1. Verify signal is one of: STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
2. Check backend validation in agent_event_subscriber.py
3. Use normalizeSignalType() for safety

## Resources

- **Pydantic Docs:** https://docs.pydantic.dev/
- **Zod Docs:** https://zod.dev/
- **OpenAPI Spec:** https://spec.openapis.org/oas/3.1.0
- **WebSocket API:** https://developer.mozilla.org/en-US/docs/Web/API/WebSocket

## Contact & Support

For issues or questions about the integration:

1. Check `docs/API_CONTRACT.md` for specification details
2. Review `docs/INTEGRATION_IMPROVEMENTS_SUMMARY.md` for implementation notes
3. Look at implementation in relevant backend/frontend files
4. Check test files for usage examples
