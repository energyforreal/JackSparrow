# Data Exchange Implementation Notes

This document describes the data flow between frontend, backend, and agent, and documents implementation details from the March 2026 data exchange error fixes.

## Architecture Overview

```
Frontend (WebSocket) <--> Backend (WebSocket Manager) <--> Agent (Redis Streams + WebSocket)
                              |
                              v
                    AgentEventSubscriber
                    (consumes trading_agent_events)
```

## Data Format Conventions

### Confidence Values

- **Backend → Frontend:** All confidence values use **0.0–1.0** range.
- **Frontend display:** `normalizeConfidenceToPercent()` converts to 0–100 for display.
- **Per-model confidence:** In `model_consensus` and `individual_model_reasoning`, confidence is always 0.0–1.0.

### Signal Values

- **Backend → Frontend:** `consensus_signal` and `signal` are discrete strings: `STRONG_BUY`, `BUY`, `HOLD`, `SELL`, `STRONG_SELL`.
- **Agent → Backend:** Agent may send numeric `consensus_signal` (-1 to +1). Backend maps via `_map_consensus_signal_to_string()` before broadcasting.

### Portfolio Format

- **get_portfolio command:** Uses `serialize_portfolio_summary()` for consistent format (matches REST API and broadcasts).
- **Broadcasts:** Same serialized format for all portfolio updates.

## Event Processing

### Event Deduplication

- Agent events have `event_id` at the **top level** of the event (not in `payload`).
- Backend extracts `event_id` from `event_dict` for deduplication.
- Redis key `processed_event:{event_id}` with 5-minute TTL prevents duplicate processing.

### Position-Closed Events

- Backend broadcasts **only** the full portfolio after position closure.
- No partial `{position_closed: {...}}` message is sent, avoiding frontend UI flicker.

## Related Documentation

- [API Contract](API_CONTRACT.md) – WebSocket message formats and types
- [Backend Documentation](06-backend.md) – WebSocket protocol and event handling
- [Architecture](01-architecture.md) – System architecture and communication flows
