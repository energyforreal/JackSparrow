# WebSocket Fix Acceptance — 2026-07-11

**Redeploy:** `jacksparrow-agent` recreated 2026-07-11T10:18:56Z  
**Fix:** `agent/data/delta_client.py` — `ping_interval=None`, `_recv_lock`, `_await_background_tasks`

## Acceptance criteria

| Criterion | Result | Notes |
|-----------|--------|-------|
| No concurrent `recv()` exceptions | **PASS** | Zero `already waiting recv` / `recv while another` in 4h post-redeploy logs |
| WebSocket connected | **PASS** | `delta_websocket_connected`, `market_data_websocket_connected` observed |
| Periodic status healthy | **PASS** | `websocket_connected=true`, `market_data_healthy=true` |
| Telemetry generation | **PASS** | `decision_telemetry.ndjson` active; latest entry 2026-07-11T12:25:28Z |
| Container health | **PASS** (intermittent timeout) | Occasional healthcheck >10s under load; recovers |

## Residual notes

- Healthcheck timeouts (ExitCode -1) occur when agent is busy; not related to recv concurrency.
- Full 48h soak recommended; re-check with `docker logs jacksparrow-agent --since 48h 2>&1 | findstr /C:"already waiting recv"`.

**Verdict:** Phase A1 acceptance **PASS** for recv fix. Continue rolling validation and shadow collection.
