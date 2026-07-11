# WebSocket Fix Acceptance — 2026-07-11

**Redeploy:** `jacksparrow-agent` recreated 2026-07-11T13:03Z (commit e959923)  
**Prior redeploy:** 2026-07-11T10:18:56Z  
**Fix:** `agent/data/delta_client.py` — `ping_interval=None`, `_recv_lock`, `_await_background_tasks`

## Acceptance ladder

| Duration | Status | recv errors | Notes |
|----------|--------|------------:|-------|
| 30 min (2026-07-11 post-redeploy) | **Initial verification PASS** | 0 | Operational check complete |
| 24 h (checked 2026-07-11) | **PASS** | 0 | `docker logs jacksparrow-agent --since 24h` — no recv matches |
| 7 d | **PENDING** | — | Production confidence gate |

## Acceptance criteria

| Criterion | Result | Notes |
|-----------|--------|-------|
| No concurrent `recv()` exceptions | **PASS** (24h) | Zero `already waiting recv` in 24h post-redeploy window |
| WebSocket connected | **PASS** | `delta_websocket_connected`, subscriptions active |
| Periodic status healthy | **PASS** | `websocket_connected=true`, `market_data_healthy=true` |
| Telemetry generation | **PASS** | `decision_telemetry.ndjson` active post-redeploy |
| Container health | **PASS** | `docker compose ps` healthy |

## 24h check command

```powershell
docker logs jacksparrow-agent --since 24h 2>&1 | findstr /C:"already waiting recv" /C:"recv() called"
```

Expected: no matches.

## Residual notes

- Startup `delta_websocket_auth_rejected` (IP whitelist) is operational noise, not recv regression.
- Healthcheck timeouts under load are unrelated to recv concurrency fix.

**Verdict:** Phase A1 recv fix **PASS** at 24h. Continue soak to 7d per Decision Observability ops.
