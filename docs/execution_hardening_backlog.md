# Execution hardening backlog (`agent/core/execution.py`)

This backlog tracks gaps called out in the architecture report against the current [`agent/core/execution.py`](../agent/core/execution.py) implementation. Items are ordered roughly by live-trading severity.

## Resolved (MAJOR-REWORK-2)

- **Atomic bracket SL/TP** — `DeltaExchangeClient.place_bracket_order()`; `ExecutionEngine` uses it when `USE_BRACKET_ORDERS=true`.
- **Fill history** — `DeltaExchangeClient.get_fills()`; `fetch_delta_fills_for_audit()` in adaptive controller.
- **Rate limiting** — token-bucket `RateLimiter` on public/private Delta API calls in [`agent/data/delta_client.py`](../agent/data/delta_client.py).

## Critical

1. **Order state machine** — **Partial:** `Order.transition_to()` in [`agent/core/execution.py`](../agent/core/execution.py); JSON + exchange rehydrate on startup; **continuous sync** in position monitor via [`sync_open_orders_with_exchange()`](../agent/core/order_persistence.py) (poll open orders against Delta).
2. **Position reconciliation** — **Done:** reconcile + `BLOCK_ENTRIES_ON_RECONCILE_DIVERGENCE` ([`agent/core/position_reconcile.py`](../agent/core/position_reconcile.py)).
3. **Idempotent order protection** — **Partial:** `client_order_id` from `correlation_id` / `idempotency_key` on place order.
4. **Partial fill handling** — **Partial:** retry remainder, cancel rest on timeout, close position ([`execution.py`](../agent/core/execution.py) `_handle_partial_fill`).
5. **Exchange failover** — **Partial:** halt `RISK_APPROVED` when Delta circuit breaker OPEN ([`agent/core/trading_controls.py`](../agent/core/trading_controls.py)).

## High

6. **Slippage policy** — **Partial:** reject fill when `ENFORCE_EXECUTION_SLIPPAGE_BPS` exceeded vs reference price.
7. **Latency monitoring** — **Partial:** p50/p95 snapshot in [`agent/core/latency_metrics.py`](../agent/core/latency_metrics.py); published to Redis `metrics:latency:execution` and exposed on `GET /api/v1/health` as `services.execution_latency`.
8. **Dead-letter / retry queue** — Failed publishes or exchange errors routed to DLQ with capped exponential backoff (complements event bus DLQ in [`agent/events/event_bus.py`](../agent/events/event_bus.py)).

## Medium

9. **Fee and tick rounding audit** — Cross-check all paths use [`agent/core/futures_utils.py`](../agent/core/futures_utils.py) consistently with venue specs.
10. **Liquidation / margin stress** — Simulation hooks in paper mode; optional exchange margin endpoint checks before large orders.

## Implementation notes

- Prefer extending `ExecutionEngine` with small composable helpers before splitting a new `agent/execution/` package, unless file size forces extraction.
- Each backlog item should land with unit tests (happy path + failure) and structured logs (`structlog`) including `correlation_id` from events.
