# Docker Deployment Debug Report
**Date:** 2026-02-23  
**Session:** Thorough debug of Docker-deployed project

## Executive Summary

A critical bug was identified and fixed that caused the agent's event processing pipeline to fail, resulting in:
- Backend health reporting agent as "down"
- Feature server, Delta Exchange, and reasoning engine all reported unavailable
- Event handlers crashing with `TypeError: _get_logger.<locals>.<lambda>() missing 1 required positional argument: 'name'`

## Findings

### 1. Root Cause: structlog Configuration Overwrite

**Location:** `agent/core/communication_logger.py`

**Problem:** The `_get_logger()` function called `structlog.configure()` with `logger_factory=lambda name: _logger`. This **overwrote the global structlog configuration** that was set by `agent/core/logging_utils.configure_logging()`.

When event handlers (e.g., `mcp_model_registry`, `feature_server`) used `structlog.get_logger()` without a name and then called `logger.info()` or `logger.error()`, structlog invoked the factory with `*_logger_factory_args` — which is empty for nameless loggers. The lambda `lambda name: _logger` requires one argument, causing:

```
TypeError: _get_logger.<locals>.<lambda>() missing 1 required positional argument: 'name'
```

**Impact:**
- Event bus message processing failed in `_process_message`
- Feature computation events failed to emit
- Model prediction events failed
- Retries failed with "Cannot retry message without event data"
- Backend health checks could not get agent status

### 2. Secondary Issues (Non-blocking)

- **event_retry_failed_no_event**: Retries fail because event data is lost when the handler crashes before ack
- **regressor_current_price_missing**: XGBoost models use fallback normalization when current price is missing in context (warning only)
- **Backend uses Redis fallback**: WebSocket to agent may not be connected; backend falls back to Redis for commands

## Fix Applied

**File:** `agent/core/communication_logger.py`

**Change:** Replaced `structlog.configure()` with `structlog.wrap_logger()` so the communication logger uses its own wrapped logger without overwriting the global structlog config.

```python
# Before (broken):
structlog.configure(
    processors=[...],
    logger_factory=lambda name: _logger,  # Overwrites global config!
    cache_logger_on_first_use=True,
)
_struct_logger = structlog.get_logger("agent_communication")

# After (fixed):
_struct_logger = structlog.wrap_logger(
    _logger,
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
)
```

## Verification Steps

1. **Rebuild agent image** (if not already done):
   ```powershell
   cd "d:\ATTRAL\Projects\Trading Agent 2"
   docker compose build agent
   ```

2. **Restart agent container**:
   ```powershell
   docker compose up -d agent
   ```

3. **Wait for health** (agent has 60s start_period):
   ```powershell
   docker compose ps agent
   ```

4. **Check agent logs** — should NOT see `TypeError` or `event_process_message_error`:
   ```powershell
   docker compose logs agent --tail 100
   ```

5. **Verify backend health** — agent and feature_server should be "up":
   ```powershell
   Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing | Select-Object -ExpandProperty Content
   ```

6. **Check for decision pipeline completion** — look for `decision_ready` or similar in agent logs after a candle closes.

## Architecture Notes

- **Agent** runs `intelligent_agent` and starts `FeatureServerAPI` (aiohttp) on port 8002
- **Backend** connects to `http://agent:8002` for feature server
- **agent-api** runs a separate FastAPI feature server on port 8003 (orchestrator may not be initialized when standalone)
- **Port mapping**: Agent's internal 8002 may be exposed as 8001 on host depending on `.env` FEATURE_SERVER_PORT

---

## Follow-up: WebSocket, Models, Delta Exchange, .env (2026-02-23)

### Analysis Summary

| Area | Status | Notes |
|------|--------|-------|
| **.env loading** | OK | `env_file: .env` on backend, agent, agent-api; Delta keys, DATABASE_URL, REDIS_URL present in containers |
| **CORS / WebSocket** | Fixed | Added `http://127.0.0.1:3000,http://127.0.0.1:3001` to CORS_ORIGINS in docker-compose (browsers may use 127.0.0.1 as Origin) |
| **Agent FEATURE_SERVER_PORT** | Fixed | Override to 8002 in docker-compose so agent listens on 8002 (backend expects agent:8002) |
| **ML models** | Check | `agent/model_storage` may be empty; models go in `agent/model_storage/xgboost/` etc. |
| **Delta Exchange** | OK | API keys and base URL loaded from .env into agent and backend |
| **Frontend build** | OK | Build args from docker-compose (which loads .env); NEXT_PUBLIC_WS_URL baked in at build |

### WebSocket Connection Error – Likely Causes

1. **CORS Origin mismatch**: Accessing via `http://127.0.0.1:3000` sends Origin `http://127.0.0.1:3000`; backend must allow it.
2. **Frontend built with wrong URL**: Rebuild after .env changes: `docker compose build frontend --no-cache`.
3. **Backend WebSocket not ready**: Ensure backend is healthy before frontend connects.

### Diagnostic Script

Run `python scripts/docker_diagnostic.py` to verify .env, container env, models, and CORS.
