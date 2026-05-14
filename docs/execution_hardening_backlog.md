# Execution hardening backlog (`agent/core/execution.py`)

This backlog tracks gaps called out in the architecture report against the current [`agent/core/execution.py`](../agent/core/execution.py) implementation. Items are ordered roughly by live-trading severity.

## Critical

1. **Order state machine** — Explicit transitions (`pending` → `open` → `partially_filled` → `filled` / `cancelled` / `rejected`) with a single authority for transitions; align internal `Order` objects with exchange-reported state on every tick or poll.
2. **Position reconciliation** — Periodic pull of exchange positions vs `PositionManager`; alert and block new risk-approved orders on divergence until reconciled.
3. **Idempotent order protection** — Client-supplied idempotency keys (or deterministic hash of symbol/side/qty/correlation_id) to prevent duplicate submissions on retries or double event delivery.
4. **Partial fill handling** — Policy for remaining quantity (cancel rest, leave working, hedge); today `Order.update_fill` supports partials; execution path must enforce exchange-specific rules and timeouts.
5. **Exchange failover** — Circuit breaker when REST/WebSocket unhealthy; read-only mode or halt `RISK_APPROVED` consumption until gateway recovers ([`agent/core/exchange_gateway.py`](../agent/core/exchange_gateway.py) integration).

## High

6. **Slippage policy** — Configurable max slip vs mid for market orders; reject or re-quote when violated (beyond paper-mode randomization).
7. **Latency monitoring** — Histogram of `RISK_APPROVED` → `ORDER_FILL` (or reject); SLO alerts.
8. **Dead-letter / retry queue** — Failed publishes or exchange errors routed to DLQ with capped exponential backoff (complements event bus DLQ in [`agent/events/event_bus.py`](../agent/events/event_bus.py)).

## Medium

9. **Fee and tick rounding audit** — Cross-check all paths use [`agent/core/futures_utils.py`](../agent/core/futures_utils.py) consistently with venue specs.
10. **Liquidation / margin stress** — Simulation hooks in paper mode; optional exchange margin endpoint checks before large orders.

## Implementation notes

- Prefer extending `ExecutionEngine` with small composable helpers before splitting a new `agent/execution/` package, unless file size forces extraction.
- Each backlog item should land with unit tests (happy path + failure) and structured logs (`structlog`) including `correlation_id` from events.
