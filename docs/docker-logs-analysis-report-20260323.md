# Docker Logs Analysis Report — 2026-03-23 (8-hour window)

**Generated:** 2026-03-23 (analysis run on host)  
**Project:** JackSparrow Trading Agent  
**Scope:** `docker compose logs --since 8h` for compose services; host `logs/*` spot-check; `prediction_audit` query.

## Data sources

| Source | Path / command | Notes |
|--------|----------------|--------|
| Agent (Docker) | `logs/docker-logs/raw-agent-8h.txt` | ~612 KB, ~1027 lines |
| Backend (Docker) | `logs/docker-logs/raw-backend-8h.txt` | ~428 KB, ~702 lines |
| Redis (Docker) | `logs/docker-logs/raw-redis-8h.txt` | ~7 KB, 50 lines |
| Frontend (Docker) | `logs/docker-logs/raw-frontend-8h.txt` | **0 bytes** — no stdout/stderr in window |
| Postgres (Docker) | `logs/docker-logs/raw-postgres-8h.txt` | **0 bytes** — no stdout/stderr in window |
| Host files | `logs/agent/agent.log` (last write ~2026-03-22) | Stale vs live Docker session; not used as primary |
| Host files | `logs/backend/*.log` | Present but **0-byte** on disk; backend evidence = Docker only |

**Caveat:** Compose uses `json-file` with `max-size: 10m` / `max-file: 3` ([`docker-compose.yml`](../docker-compose.yml)). `--since 8h` requests eight hours, but **actual span** in agent logs is roughly **2026-03-23T02:33Z → ~04:15Z** (~2h) — consistent with containers having started within the last eight hours or low prior volume.

## Executive summary

- **Stack:** All five services (`agent`, `backend`, `frontend`, `postgres`, `redis`) were **running** at analysis time.
- **AI signals:** **8** `mcp_orchestrator_decision_ready_emitted` events; all sampled show **HOLD** with confidence **~0.42–0.44** (non-zero; no placeholder 0% consensus in this sample).
- **ML path:** **0** `mcp_orchestrator_prediction_request_failed`; **16** `advanced_consensus_calculated` (pairs with registry + consensus logs); **2** models healthy in sampled `model_predictions_health_status`.
- **Anomalies:** **1** Delta REST **`401 Unauthorized`** on **`/v2/history/candles`** (hourly history); tickers returned **200 OK**. **2** Delta websocket `delta_websocket_connection_lost` (reconnect followed). **1** backend `agent_service_websocket_timeout`. **`prediction_audit`** table is **empty** (no persisted audit rows for any period).
- **Noise:** Naive grep for `401` over-counts (e.g. ephemeral ports like `127.0.0.1:40142`). Use **`401 Unauthorized`** for API auth.

## AI signal cadence vs `AGENT_INTERVAL`

- Default interval in compose: **`AGENT_INTERVAL=15m`**.
- **8** distinct `mcp_orchestrator_decision_ready_emitted` timestamps in ~2h of captured activity → **above** one-per-15m (expected ~8 in 2h), so **cadence is plausible** for the observed window.
- Duplicated `decision_ready` close together (e.g. 02:33:36 and 02:33:53) likely separate pipeline stages or triggers, not a failure mode by itself.

## Agent — ML and orchestration

| Pattern | Count | Assessment |
|---------|------:|------------|
| `mcp_orchestrator_decision_ready_emitted` | 8 | Signals emitted; all HOLD in sample |
| `confidence_calibration_completed` | 8 | Matches decision cycles |
| `mcp_orchestrator_prediction_request_failed` | 0 | No orchestrator prediction failures |
| `advanced_consensus_calculated` | 16 | Consensus engine active |
| `trading_entry_rejected` (e.g. `hold_signal`) | 8 | Expected when signal is HOLD |
| `model_predictions_health_status` / healthy models | present | 2 models, healthy |

Sample consensus: **adaptive** method, **ranging** regime, **high** risk level, ~0.527 confidence from ensemble — consistent with downstream calibration ~0.42–0.44.

## Agent — market data and exchange

| Pattern | Count | Notes |
|---------|------:|-------|
| `401 Unauthorized` (HTTP history candles) | 1 | Auth/scopes or signing issue on **history** endpoint only |
| `delta_websocket_connection_lost` | 2 | Brief disconnects; reconnect logged |
| Tickers `HTTP/1.1 200 OK` | many | Public/market reads OK |

**Recommendation:** Verify API key permissions and signed vs unsigned routes for **`/v2/history/candles`** on Delta India.

## Agent — WebSocket (agent server + backend client)

- **`agent_websocket_*`** lines: **165** (includes connect/disconnect noise, health probes).
- Backend connects to agent feature/WS as designed; no sustained `ConnectionRefused` to `ws://backend` in this capture.

## Backend

| Pattern | Count | Notes |
|---------|------:|-------|
| `health_endpoint_deprecated` | 82 | **Expected** noise from health checks hitting deprecated REST `/health` |
| `outbound_agent_command_ws_*` | 182 each | Normal backend → agent command traffic |
| HTTP to `http://agent:8002/api/v1/models` 200 | 161 | Feature server reachable |
| `agent_service_websocket_timeout` | 1 | **Minor** — one timeout; monitor if it grows |
| `agent_event_subscriber` / `unknown_event_type` / `position_not_created` | 0 | No subscriber errors in this window |

## Frontend and Postgres (Docker stdout)

- **Empty** log files for **frontend** and **postgres** in the 8h pull: typical when processes log to files inside volumes or log level is quiet. **Not** evidence that services are down (they were **running**).

## Redis

- **50** lines, no errors flagged in quick scan; no `FATAL` / connection storm patterns in `raw-redis-8h.txt`.

## Database — `prediction_audit`

```sql
SELECT COUNT(*) FROM prediction_audit;        -- 0
SELECT COUNT(*) ... last 8 hours;               -- 0
```

The table exists but **is not populated**. Log-based signal verification is the only evidence in this run; consider wiring inserts if audit persistence is required.

## Raw artifacts

Captured under **`logs/docker-logs/`**:

- `raw-agent-8h.txt`
- `raw-backend-8h.txt`
- `raw-redis-8h.txt`
- `raw-frontend-8h.txt` (empty)
- `raw-postgres-8h.txt` (empty)

## Related documentation

- Prior patterns and flow notes: [`docs/docker-logs-and-compliance-report.md`](docker-logs-and-compliance-report.md)
- Compose logging limits: [`docker-compose.yml`](../docker-compose.yml)
