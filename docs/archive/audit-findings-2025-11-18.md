# Project Audit Findings

**Date**: 2025-11-18  
**Audit Type**: Full-stack review  
**Scope**: Backend, agent, frontend, deployment tooling, documentation

---

## 🔴 Critical Issues

### 1. Backend ↔ Agent commands never complete

**Location**: `backend/services/agent_service.py`, `backend/core/redis.py`, `agent/core/intelligent_agent.py`

**Issue**: The backend waits for replies by polling `get_response()` (which looks up a Redis key such as `response:<id>`), but the agent pushes replies into a Redis *list* (`lpush(f"response:{request_id}", ...)`). No code moves the list entry into the key the backend reads, so every command times out.

**Impact**:
- `/api/v1/predict`, `/api/v1/trade/execute`, and every admin control endpoint always return "Agent service unavailable".
- Health checks that ask the agent for status report "unknown/degraded", breaking monitoring and autoscaling.

**Recommendation**:
- Use one channel: either let the backend block on `brpop` like the agent does, or keep the key-value cache and change the agent to `setex` the response. Add regression tests so async interactions don't silently deadlock again.

---

### 2. Trading/admin APIs are unauthenticated

**Location**: `backend/api/routes/*.py`

**Issue**: None of the `trading`, `portfolio`, or `admin` routers depend on `require_auth` / API-key verification from `backend/api/middleware/auth.py`. Anyone who can reach the backend can trigger predictions, submit trades, or call `emergency_stop` without credentials.

**Impact**:
- Remote execution of trades and control-plane actions.
- Violates security requirements defined in `docs/14-project-rules.md`.

**Recommendation**:
- Add `dependencies=[Depends(require_auth)]` (or route-level decorators) to every protected router.
- Provide 403/401 responses for anonymous clients and document required headers in the frontend service.

---

### 3. Delta Exchange client never authenticates requests

**Location**: `agent/data/delta_client.py`

**Issue**: Requests are sent with headers `{ "api-key": ..., "api-secret": ... }` but the Delta Exchange API requires HMAC signatures (`timestamp`, `signature`, etc.). Every trade placement call therefore fails with 401/403, so the agent can never execute the orders it approves.

**Impact**:
- All executions and market data calls relying on authenticated endpoints fail.
- Risk of hitting rate limits or being blocked for invalid authentication attempts.

**Recommendation**:
- Implement the documented signing scheme (message = timestamp + method + path + body, HMAC-SHA256 with api-secret).
- Add retry/backoff plus circuit-breaker integration tests so misconfiguration is caught before production.

---

## ⚠️ Medium Priority Issues

### 4. Backend config defaults still break on empty env vars

**Location**: `backend/core/config.py`

**Issue**: `jwt_secret_key` and `api_key` have defaults, but an empty string provided by the environment overrides the default with an invalid value. Pydantic raises validation errors at startup (`Field required`) which is still visible in `logs/backend.log`.

**Recommendation**: Reintroduce the `field_validator(..., mode="before")` that converts `""` to `None`, or set `validate_default=True`. Mirror the fix for the agent config as well.

---

### 5. Frontend dashboard never renders live data

**Location**: `frontend/app/components/Dashboard.tsx`, `frontend/hooks/useAgent.ts`

**Issue**:
- `Dashboard` keeps local `useState` placeholders (`signal`, `health`, `positions`, etc.) that never get populated from hooks.
- `useAgent` only fetches REST fallbacks when the WebSocket succeeds; on connection failures, the UI stays blank even though the API is reachable.

**Impact**:
- Production dashboards show "Loading…" forever when the WS port is blocked (common in staging) or before the agent starts sending messages.
- Engineers cannot monitor the system or inspect reasoning chains.

**Recommendation**:
- Replace the placeholder state with the data returned by `useAgent`.
- Always fetch initial portfolio + status via REST, independent of WebSocket state, and provide skeletons for late-arriving WS snapshots.

---

### 6. Portfolio tables choke on stringified decimals

**Location**: `frontend/app/components/ActivePositions.tsx`, `frontend/types/index.ts`

**Issue**: API responses serialize SQLAlchemy `DECIMAL` columns as strings, but the UI types expect numbers and immediately call `.toLocaleString()` on them. When real data arrives the component throws ("toLocaleString is not a function") and React unmounts the table.

**Recommendation**: Normalize numeric fields (e.g., `Number(position.entry_price)`) or change the API models to emit floats. Update the TypeScript types to match the actual payload and add defensive parsing.

---

### 7. Backend container health check hits a non-existent path

**Location**: `docker-compose.yml` (backend service), `backend/api/routes/health.py`

**Issue**: The FastAPI router exposes `GET /api/v1/health`, but the Compose health check uses `curl -f http://localhost:8000/health`. The command always exits 22, so Docker restarts the backend endlessly even when it is healthy.

**Recommendation**: Change the probe to `/api/v1/health` (or expose a lightweight `/healthz` route) and keep the same logic in k8s/Compose manifests.

---

### 8. Tooling ignores dependency install failures & lacks .env templates

**Locations**: `tools/commands/start_parallel.py`, `Makefile`, project root

**Issues**:
- `ensure_dependencies()` runs `pip install ...` and `npm install` with `check=False`, so dependency failures are silently ignored and services crash later with import errors.
- There are still no `.env.example` files even though scripts instruct users to "copy backend/.env.example".
- The `make stop`/`make clean` fallbacks (used on Windows because `stop.ps1`/`clean.ps1` do not exist) call `pkill`, `kill`, and `find`, which fail immediately on PowerShell.

**Recommendation**:
- Capture the subprocess return codes and raise/log actionable errors (with an opt-out flag for CI).
- Add template env files for `backend`, `agent`, and root, keeping secrets blank.
- Provide platform-specific stop/clean scripts and have the Makefile delegate to them the same way `start/audit/error` already do.

---

## ✅ Positive Findings

1. **Structured logging everywhere** – Backend and agent services consistently emit `service=…` structured events (`backend/api/main.py`, `agent/core/intelligent_agent.py`), which made debugging straightforward.
2. **Event-driven agent core** – The state machine plus event bus (`agent/core/state_machine.py`, `agent/events/event_bus.py`) already models the richer states defined in the reference specs, so adding the missing documentation is mostly a writing task.
3. **Containerized stack parity** – Compose brings up Postgres, Redis, agent, backend, and frontend with health checks and shared volumes, giving a good baseline for future CI/CD automation once the probe bug is fixed.

---

## 📋 Recommendations Summary

### Immediate (Critical)
1. Fix the Redis response plumbing so API ⇄ agent RPCs work.
2. Enforce authentication/authorization on every trading and admin route.
3. Implement the proper Delta Exchange signing scheme so executions succeed.

### Short Term (Medium)
4. Normalize config defaults, create `.env.example` templates, and wire the backend health check to the correct path.
5. Replace placeholder frontend state with real data + type-safe parsing so the dashboard reflects live conditions.
6. Harden `start_parallel.py` and Makefile scripts to fail fast (and work on Windows) when dependencies or teardown steps break.

### Longer Term
7. Add integration tests that cover backend↔agent RPCs, WS fallbacks, and container health probes.
8. Extend documentation (`docs/04-features.md`, `docs/05-logic-reasoning.md`) so the implemented state machine, context, and circuit breaker logic stay in sync with the build.

---

## 📊 Audit Snapshot

- **Files reviewed**: 26
- **Critical issues**: 3
- **Medium issues**: 5
- **Positive findings**: 3
- **Tests executed**: Not run (code/read-only audit)

---

## ✅ Next Steps

1. File tickets for each finding (linking to the code references above).
2. Prioritize critical fixes before enabling any live trading.
3. After remediation, rerun the audit (or at least API/agent integration tests) to confirm RPC, authentication, and deployment paths are healthy again.

