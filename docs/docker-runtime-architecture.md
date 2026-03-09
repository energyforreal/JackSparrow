## Docker Runtime Architecture and Logs

This document explains how the JackSparrow stack behaves **at runtime when deployed with Docker**:
which containers run, how they communicate, how market data flows through the system, and how
logging works (both Docker engine logs and in-app logs) during a live run.

It is a **runtime view** that complements:
- `docs/01-architecture.md` (logical architecture)
- `docs/DOCKER_DEPLOYMENT.md` (how to build and deploy with Docker)
- `docs/12-logging.md` (centralized logging design)

---

## 1. High‑Level Runtime Architecture

### 1.1 Overview & Scope

- **Goal**: describe what is actually running inside Docker, how the services talk to each
  other, and what an operator can see in real time via logs and health endpoints.
- **Scope**:
  - Containers and network topology
  - Real‑time communication between agent, backend, frontend, Postgres, Redis, and Delta Exchange
  - Data lifecycle: market data → features/models → decisions → trades/positions → UI
  - Logging: Docker `json-file` logs, structured application logs, and analysis tooling

### 1.2 Containers and Network Layout

At runtime, `docker-compose.yml` brings up the following long‑running containers on the
`jacksparrow-network` bridge:

- **postgres (`jacksparrow-postgres`)**
  - TimescaleDB/PostgreSQL instance for trades, positions, portfolio and other state.
  - Exposed on host as `${POSTGRES_PORT:-5432}` → container `5432`.
- **redis (`jacksparrow-redis`)**
  - Redis cache/queue for command/response queues and auxiliary data.
  - Exposed on host as `${REDIS_PORT:-6379}` → container `6379`.
- **agent (`jacksparrow-agent`)**
  - Python AI trading agent and feature server.
  - Internal ports:
    - `8002` – feature server HTTP + agent WebSocket server.
  - Exposed on host as `${FEATURE_SERVER_PORT:-8002}` → container `8002`.
- **backend (`jacksparrow-backend`)**
  - FastAPI backend API + WebSocket server.
  - Exposed on host as `${BACKEND_PORT:-8000}` → container `8000`.
- **frontend (`jacksparrow-frontend`)**
  - Next.js dashboard UI, talking to backend over HTTP + WebSocket.
  - Exposed on host as `${FRONTEND_PORT:-3000}` → container `3000`.

All containers share the same **bridge network**:

```mermaid
flowchart LR
  subgraph jacksparrowNetwork["Docker bridge network: jacksparrow-network"]
    frontend["frontend\n(Next.js UI)"]
    backend["backend\n(FastAPI API + WS)"]
    agent["agent\n(Trading Agent + Feature Server)"]
    postgres["postgres\n(TimescaleDB)"]
    redis["redis\n(Redis)"]

    frontend <--> backend
    backend <--> agent
    backend <--> postgres
    backend <--> redis
    agent <--> postgres
    agent <--> redis
  end
```

On this network the containers address each other by **service name**:

- `postgres:5432`, `redis:6379`, `agent:8002`, `backend:8000`.
- The host accesses the stack using mapped ports, typically `localhost:8000`, `localhost:3000`,
  `localhost:8002`, etc.

---

## 2. Real‑Time Communication Flows Between Services

### 2.1 Backend ↔ Agent

There are **three** communication paths between backend and agent; WebSocket is the primary one.

- **Agent → Backend (events)** – WebSocket
  - Backend exposes `/ws/agent` in `backend.api.main.agent_websocket_endpoint`.
  - Agent configuration (`agent/core/config.py`):
    - `backend_websocket_url` (alias `BACKEND_WS_URL`, default `ws://localhost:8000/ws/agent`).
  - In Docker (`docker-compose.yml`):
    - Agent env: `BACKEND_WS_URL=ws://backend:8000/ws/agent`.
  - At runtime the agent **connects out** to `ws://backend:8000/ws/agent` and streams events:
    - `decision_ready`, `order_fill`, `position_closed`, state transitions, health events, etc.

- **Backend → Agent (commands / feature requests)** – HTTP + optional WebSocket
  - Backend settings (`backend/core/config.py`):
    - `feature_server_url` (`FEATURE_SERVER_URL`, default `http://localhost:8002`).
    - `agent_websocket_url` (`AGENT_WS_URL`, default `ws://localhost:8002`).
    - `use_agent_websocket` (`USE_AGENT_WEBSOCKET`, default `True`).
  - In Docker:
    - Backend env: `FEATURE_SERVER_URL=http://agent:8002`.
    - `AGENT_WS_URL` should be set to `ws://agent:8002` via `.env` for WebSocket control.
  - Runtime behavior:
    - For **feature requests** and some control flows, backend calls `http://agent:8002/...`.
    - When `use_agent_websocket=True`, backend also maintains an outbound WebSocket connection
      to the agent’s WebSocket server at `ws://agent:8002` for low‑latency command/response
      (e.g., synchronous prediction requests).

- **Redis command/response queues (fallback/auxiliary)**
  - Backend config:
    - `agent_command_queue`, `agent_response_queue` (default `agent_commands`, `agent_responses`).
  - Agent config mirrors the same queue names.
  - If WebSocket connectivity is disabled or unavailable, backend can fall back to Redis queues
    for issuing commands and receiving responses with higher latency but stronger isolation.

### 2.2 Backend ↔ Frontend

- **HTTP API**
  - Backend exposes REST endpoints at `http://backend:8000/api/v1/...`.
  - Frontend build args/env (`docker-compose.yml`):
    - `NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL:-http://localhost:8000}`.
  - In a default Docker run, users connect to `http://localhost:3000` (frontend), and browser
    JavaScript calls `NEXT_PUBLIC_API_URL` – usually `http://localhost:8000`.

- **WebSocket (real‑time UI updates)**
  - Backend exposes `/ws` (see `backend.api.main.websocket_endpoint`).
  - Frontend env:
    - `NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL:-ws://localhost:8000/ws}`.
  - Frontend connects from the browser to `ws://localhost:8000/ws` and receives unified
    `data_update`, `agent_update`, and `system_update` messages as documented in
    `docs/01-architecture.md` and `frontend/hooks/useTradingData.ts`.

**Data types pushed over WebSocket** include:

- `data_update` / `resource: "signal"` – AI signal and confidence (BUY/SELL/HOLD).
- `data_update` / `resource: "trade"` – new paper trades and fills.
- `data_update` / `resource: "portfolio"` – portfolio value, open positions, PnL.
- `data_update` / `resource: "market"` – recent market ticks.
- `data_update` / `resource: "model"` – model‑level predictions/consensus.
- `agent_update` / `resource: "agent"` – agent state machine status.
- `system_update` / `resource: "health"` / `"time"` – health and time sync.

### 2.3 Services ↔ Infrastructure (Postgres, Redis)

Both backend and agent read DB/cache configuration from the **single root `.env`** via their
Pydantic settings (`backend/core/config.py`, `agent/core/config.py`).

- **Postgres**
  - In Docker compose (backend/agent services):
    - `DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}`.
  - At runtime both services talk to `postgres:5432` on the Docker network.
  - Used for:
    - Persisting trades, positions, portfolio snapshots, and other domain state.
    - Storing audit‑relevant data for paper trades.

- **Redis**
  - In Docker compose:
    - `REDIS_URL=redis://redis:6379/0`.
  - Used for:
    - Command/response queues between backend and agent.
    - Caching of market/feature data and other ephemeral state (depending on configuration).

### 2.4 External Exchange ↔ Agent

The agent is the only container that talks to **Delta Exchange** directly.

- **REST API**
  - Env in agent config:
    - `delta_exchange_base_url` (`DELTA_EXCHANGE_BASE_URL`, default `https://api.india.delta.exchange`).
    - `delta_exchange_api_key` / `delta_exchange_api_secret`.
  - Used for:
    - Pulling historical candles and ticker snapshots.
    - Placing/cancelling orders in **live trading mode** (paper mode simulates fills instead).

- **WebSocket API**
  - Agent settings:
    - `websocket_url` (`WEBSOCKET_URL`, default `wss://socket.india.delta.exchange`).
    - `websocket_enabled`, `websocket_reconnect_attempts`, `websocket_reconnect_delay`, etc.
  - Used for:
    - Real‑time market data streams (ticker/market depth).
    - Driving the internal market events that eventually result in feature updates and signals.

---

## 3. Data Lifecycle: Fetching, Analysis, Exchange, Relaying

### 3.1 Market Data Ingestion Path

At runtime the agent continuously ingests market data and converts it into internal events:

1. **External stream/polling**
   - Agent connects to Delta Exchange WebSocket at `websocket_url` for live ticks.
   - If WebSocket is unavailable, the agent falls back to REST polling using
     `fast_poll_interval` / `websocket_fallback_poll_interval`.
2. **Market events inside the agent**
   - Incoming ticks are normalized and emitted as internal events (e.g. `MarketTickEvent`,
     price‑fluctuation events) via the agent’s event bus.
   - `agent/data/market_data_service.py` and related components update the market context and,
     when thresholds are crossed, signal that a new analysis is needed.
3. **Context updates**
   - Recent prices, candles and derived statistics are stored in memory and, where necessary,
     persisted to Postgres and/or cached in Redis.
4. **Downstream triggers**
   - These internal events trigger feature computation and ML pipelines that feed into the
     decision and execution chain.

### 3.2 ML Feature & Model Pipeline

Once a relevant market event occurs (e.g. price fluctuation, candle close):

1. **Feature engineering**
   - `agent/data/feature_engineering.py` and related feature server components compute
     technical indicators and higher‑level features.
   - The feature server exposes these via the MCP Feature Protocol and is accessible to both
     the agent core and backend (via `FEATURE_SERVER_URL`).
2. **Model predictions**
   - Model nodes under `agent/models/*.py` (XGBoost, LightGBM, LSTM, Transformer, etc.) load
     trained models from `agent/model_storage` (mounted into the container).
   - MCP model registry coordinates model inference, returning predictions and confidences.
3. **Reasoning and orchestration**
   - `agent/core/mcp_orchestrator.py` aggregates model predictions and passes them to the
     reasoning engine (`agent/core/reasoning_engine.py`).
   - The reasoning engine runs the documented 6‑step reasoning chain
     (`docs/05-logic-reasoning.md`), calibrating confidence and recording a decision context.
4. **Decision events**
   - A `DecisionReadyEvent` is emitted with:
     - Direction (BUY/SELL/HOLD),
     - Final confidence,
     - Model consensus and reasoning metadata.
   - This event is then propagated to the backend via the agent→backend WebSocket.

### 3.3 Trades, Positions, and Portfolio Updates

Once a decision is available:

1. **Trading handler and risk checks**
   - `agent/events/handlers/trading_handler.py` subscribes to `DecisionReadyEvent`.
   - It validates confidence, checks for open positions, applies risk rules (including
     stop‑loss, take‑profit, trailing stop and maximum drawdown) and either:
     - Emits a `RiskApprovedEvent` for execution, or
     - Logs a rejection and does nothing.
2. **Execution and paper fills**
   - `agent/core/execution.py` consumes `RiskApprovedEvent`.
   - In **paper mode**, it calculates a simulated fill price using Delta ticker data and
     configurable spread/slippage, then emits an `OrderFillEvent` and logs to
     `logs/agent/agent.log` and paper‑trade logs.
   - Positions and trades are persisted to Postgres via the backend persistence layer.
3. **Backend event subscriber**
   - `backend/services/agent_event_subscriber.py` listens on the agent WebSocket stream.
   - For decision, order‑fill and position‑closed events it:
     - Updates DB models (trades, positions, portfolio).
     - Emits WebSocket messages to frontend clients via `/ws`.
4. **Frontend updates**
   - The frontend hook `useTradingData` merges `signal`, `model`, `portfolio`, `trade` and
     `health` updates from the backend WebSocket into a single UI state.
   - Users see:
     - Current signal/confidence,
     - Open positions and PnL,
     - Recent trades,
     - Agent and system health.

### 3.4 End‑to‑End Sequence (Tick → Signal → UI)

```mermaid
sequenceDiagram
  participant Delta as DeltaExchange
  participant Agent as AgentService
  participant Backend as BackendAPI
  participant Frontend as FrontendUI

  Delta->>Agent: Market tick (WS / REST)
  Agent->>Agent: Update market context & features
  Agent->>Agent: Run models + reasoning\n(DecisionReadyEvent)
  Agent-->>Backend: WS /ws/agent\nDecisionReadyEvent
  Backend->>Backend: Update DB, publish signal\n(agent_event_subscriber)
  Backend-->>Frontend: WS /ws\n data_update(resource=\"signal\")
  Frontend->>Frontend: Update dashboard state
```

### 3.5 End‑to‑End Sequence (Decision → Trade → Portfolio)

```mermaid
sequenceDiagram
  participant Agent as AgentService
  participant Backend as BackendAPI
  participant DB as Postgres
  participant Frontend as FrontendUI

  Agent->>Agent: DecisionReadyEvent\npasses risk checks
  Agent->>Agent: Simulate paper fill\n(OrderFillEvent)
  Agent-->>Backend: WS /ws/agent\nOrderFillEvent + PositionOpened/Closed
  Backend->>DB: Persist trade + position
  Backend-->>Frontend: WS /ws\n data_update(resource=\"trade\"/\"portfolio\")
  Frontend->>Frontend: Refresh trades, positions, PnL
```

---

## 4. Docker‑Specific Runtime Behaviour & Nuances

### 4.1 Startup Ordering and Health Checks

`docker-compose.yml` uses `depends_on` with health conditions to enforce startup order:

1. **Postgres** and **Redis**
   - Health checks:
     - Postgres: `pg_isready -U ... -d ...`.
     - Redis: `redis-cli ping`.
2. **Agent**
   - `depends_on` Postgres and Redis with `condition: service_healthy`.
   - Health check: `python -m agent.healthcheck`.
3. **Backend**
   - `depends_on` Postgres, Redis, Agent with `condition: service_healthy`.
   - Health check: `curl -f http://localhost:${BACKEND_PORT}/api/v1/health`.
4. **Frontend**
   - `depends_on` Backend with `condition: service_healthy`.
   - Health check: Node script performing HTTP GET on `/`.

In practice this means:

- The agent will not start until the DB/cache are live.
- The backend will not be marked healthy until both infra and agent are healthy.
- The frontend will not be marked healthy until the backend is responding to HTTP.

### 4.2 Environment Wiring Inside Containers

The **root `.env` file is the single source of truth** for config (see `docs/DOCKER_DEPLOYMENT.md`):

- Backend and agent services use `env_file: - .env` plus additional `environment:` overrides
  (e.g., `DATABASE_URL` rewritten with `postgres` host).
- Frontend receives its config only via `environment:` and Docker build args; it does *not*
  read `.env` at runtime inside the container.
- When running inside Docker:
  - DB/Redis hosts must be `postgres` / `redis`, not `localhost`.
  - Backend → agent URLs must use service names, e.g. `http://agent:8002`, `ws://agent:8002`.
  - Agent → backend URL is `ws://backend:8000/ws/agent`.

The same `.env` file can be reused for local, non‑Docker runs, but **URL hostnames differ**
(`localhost` instead of service names).

### 4.3 Dev vs Prod Docker Stacks

`docker-compose.dev.yml` overrides the base stack for development:

- **Backend / Agent / Frontend** use `Dockerfile.dev` images with **source code mounted** into
  the containers for hot‑reload.
  - Backend command: `uvicorn backend.api.main:app --reload ...`.
  - Frontend command: `npm run dev`.
  - Agent uses a dev image with code mounted and Python watching for file changes.
- **Logging levels** are raised:
  - Backend: `LOG_LEVEL=${BACKEND_LOG_LEVEL:-DEBUG}`.
  - Agent: `LOG_LEVEL=${AGENT_LOG_LEVEL:-DEBUG}`.

Logical data and communication flows remain the same; only build strategy and verbosity differ.

---

## 5. Logging in a Dockerized Run

### 5.1 Docker Engine Logs (json‑file Driver)

Every service in `docker-compose.yml` is configured with:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

Implications:

- Docker captures each container’s **stdout/stderr** as structured JSON log files on the host.
- Logs are rotated when they reach ~10 MB, keeping up to 3 files per container.
- Operators use:
  - `docker compose logs` (all services) or
  - `docker compose logs backend`, `docker compose logs agent`, etc.

For more advanced workflows, helper scripts described in
`docs/DOCKER_DEPLOYMENT.md` and `.cursor/commands/docker-logs.md` can:

- Filter by service and severity.
- Tail logs interactively (`-f`).
- Export logs to `logs/docker-logs/...` for later analysis.

### 5.2 Application Log Files & Structure

In addition to Docker’s `json-file` logs, the services write **structured JSON logs to bind‑mounted
directories** (see `docs/12-logging.md`):

- **Backend**
  - Host: `logs/backend/` (mounted into container as `/logs`).
  - Files:
    - `backend.log` – full log stream.
    - `errors.log` – ERROR and CRITICAL only.
    - `warnings.log` – WARNING only.
- **Agent**
  - Host: `logs/agent/` (mounted as `/logs`), plus `logs/paper_trades/` for trade logs.
  - Files:
    - `agent.log` – full agent log stream.
    - `errors.log`, `warnings.log` – severity‑filtered logs.
- **Frontend**
  - Host: `logs/frontend/` (mounted as `/logs`).
  - Contains server‑side Next.js logs (via `pino`/`winston` stack).

These logs:

- Follow the JSON schema defined in `docs/12-logging.md` (fields like `timestamp`, `service`,
  `component`, `level`, `session_id`, etc.).
- Are **cleared or archived on startup** by the logging bootstrapper to guarantee a fresh
  view per run (see “Startup Clearing Procedure” in `docs/12-logging.md`).
- Are the primary source for **compliance and incident analysis**, because they contain
  rich context (correlation IDs, reasoning metadata, trading decisions).

### 5.3 Log Configuration via Environment Variables

Both backend and agent read logging configuration from env vars:

- **Common**
  - `LOG_LEVEL` – global minimum severity (default `INFO`).
  - `LOG_FORWARDING_ENABLED` / `LOG_FORWARDING_ENDPOINT` – send logs to a remote collector.
  - `LOG_INCLUDE_STACKTRACE` – include stack traces in log payloads.
- **Service‑specific**
  - Backend: `BACKEND_LOG_LEVEL` (overrides `LOG_LEVEL` for backend).
  - Agent: `AGENT_LOG_LEVEL` (overrides `LOG_LEVEL` for agent).
- **Communication logging**
  - `ENABLE_COMMUNICATION_LOGGING` – enable detailed logging of inter‑service communication.
  - `LOG_WEBSOCKET_PAYLOADS` – include WebSocket payload snippets (subject to truncation).
  - `MAX_LOG_PAYLOAD_SIZE` – bytes cap per logged payload.
  - `COMMUNICATION_SENSITIVE_FIELDS` – keys that must be redacted from logs.

In Docker:

- Backend env: `LOG_LEVEL=${BACKEND_LOG_LEVEL:-INFO}`.
- Agent env: `LOG_LEVEL=${AGENT_LOG_LEVEL:-INFO}` and `LOGS_ROOT=/logs`.
- Dev override (`docker-compose.dev.yml`) bumps these to `DEBUG` by default, making
  Docker logs and `/logs/...` files much more verbose for troubleshooting.

### 5.4 Log Analysis and Compliance Workflows

Runtime logs are typically consumed in three layers:

1. **Quick inspection (Docker logs)**
   - `docker compose logs -f` – watch all services.
   - `docker compose logs -f backend` – backend only.
   - `docker compose logs --tail=200 agent` – recent agent logs, all severities.
2. **Structured inspection (application log files)**
   - Use `jq`, editors, or viewer scripts on:
     - `logs/backend/backend.log`, `logs/backend/errors.log`, etc.
     - `logs/agent/agent.log`, `logs/agent/errors.log`, etc.
   - Combine with the analysis tools documented in `docs/12-logging.md`:
     - `tools/commands/analyze-errors.py` – aggregates and summarizes error patterns.
     - `tools/commands/view-errors.py` – interactive filtering/tail of error logs.
3. **Compliance and behavior verification**
   - `docs/docker-logs-and-compliance-report.md` and
     `docs/docker-logs-analysis-report-current.md` show how to:
     - Capture `docker compose logs --no-log-prefix` output.
     - Grep for errors/warnings and key patterns (e.g. `decision_ready`,
       `execution_order_fill_published`, `paper_trade_state_reset`).
     - Verify that AI signals and paper trades behave as documented (no fake HOLD 0%,
       exit conditions working, reset behavior correct).
   - These reports are typically regenerated per run and stored as timestamped markdown
     files under `docs/` and `docs/archive/`.

---

## 6. Operator Real‑Time View & Recipes

### 6.1 “What Is Happening Right Now?” Checklist

For a running Docker deployment, an operator can quickly assess system health with:

- **Container status**
  - `docker compose ps` – check containers and health statuses.
- **High‑level health**
  - Browser: open `http://localhost:3000` for the UI.
  - `curl http://localhost:8000/api/v1/health` – backend health and composite score.
- **Live logs**
  - `docker compose logs -f backend agent` – see API + agent activity.
  - For more detail, inspect `logs/backend/backend.log` and `logs/agent/agent.log`.
- **Trading activity**
  - Look for:
    - `DecisionReadyEvent` / `decision_ready` logs in agent and backend.
    - `execution_order_fill_published`, `OrderFillEvent` logs in agent.
    - Portfolio/position updates in backend logs and the dashboard UI.

### 6.2 Common Investigation Paths

- **No signals visible in the UI**
  - Check `docker compose logs backend agent` for:
    - Agent event stream on `/ws/agent` (connection errors, subscription logs).
    - `decision_ready` logs in agent and their propagation in backend.
  - Confirm frontend WebSocket connectivity:
    - Backend logs for `/ws` connections.
    - Browser dev tools: WebSocket frames on `ws://localhost:8000/ws`.

- **Trades not appearing in portfolio**
  - Verify agent execution:
    - `execution_order_fill_published` and `OrderFillEvent` logs in `logs/agent/agent.log`.
  - Verify backend persistence:
    - `agent_event_subscriber` logs in `logs/backend/backend.log` for order‑fill handling.
  - Ensure Postgres is healthy:
    - `docker compose logs postgres`.
    - Backend health endpoint status and DB connectivity logs.

- **Exchange connectivity or data issues**
  - Inspect agent logs for:
    - Delta REST errors, circuit‑breaker messages.
    - WebSocket reconnect attempts and error codes.
  - If a circuit breaker is open (see `docs/01-architecture.md` for breaker behavior),
    the agent will log degraded state and pause trading until connectivity is restored.

---

## 7. Related Documentation

- `docs/01-architecture.md` – full system architecture, data flow, and communication protocols.
- `docs/03-ml-models.md` and `docs/ML-MODELS-AND-DATA.md` – model and data details that
  underpin the feature and prediction pipeline.
- `docs/04-features.md` – feature set of the trading agent, including risk and monitoring.
- `docs/05-logic-reasoning.md` – reasoning engine, decision pipeline and confidence handling.
- `docs/06-backend.md` – backend implementation, routes, and WebSocket details.
- `docs/10-deployment.md` and `docs/DOCKER_DEPLOYMENT.md` – deployment and environment setup.
- `docs/12-logging.md` – logging architecture, schema, and analysis tools.
- `docs/docker-logs-analysis-report-current.md` and
  `docs/docker-logs-and-compliance-report.md` – examples of real Docker log analyses and
  compliance reports.

