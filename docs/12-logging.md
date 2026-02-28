# Logging Documentation

## Overview

This document defines the centralized logging system for the JackSparrow trading agent.  
The logging system ensures that every service—backend API, AI agent services, frontend web application, task runners, data services, and infrastructure components—records all potential errors, warnings, and operational insights in a consistent, queryable format.  
Logs must be reset whenever a new run (development session, deployment, or automated pipeline) begins to guarantee a fresh view of system behaviour.

---

## Table of Contents

- [Overview](#overview)
- [Objectives](#objectives)
- [Scope](#scope)
- [Functional Requirements](#functional-requirements)
- [Architecture](#architecture)
- [Log Schema](#log-schema)
- [Service Integration](#service-integration)
- [Startup Clearing Procedure](#startup-clearing-procedure)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Observability Integration](#observability-integration)
- [Operational Procedures](#operational-procedures)
- [Testing the Logging System](#testing-the-logging-system)
- [Security & Compliance](#security--compliance)
- [Implementation Roadmap](#implementation-roadmap)
- [References](#references)
- [Change Log](#change-log)

---

## Objectives

1. **Complete Error Visibility**  
   Capture every exception, rejection, degraded state, and anomaly emitted by the application or infrastructure layers.

2. **Service-Parity**  
   Apply the same logging standards across all services to maintain comparability.

3. **Fresh Start Compliance**  
   Clear or archive existing logs at the start of every new run (local or deployed) to avoid obscuring new issues.

4. **Traceability & Diagnostics**  
   Provide correlation identifiers to trace multi-service flows and root-cause issues quickly.

5. **Operational Readiness**  
   Integrate with monitoring, alerting, and on-call procedures for production-readiness.

---

## Scope

The logging plan applies to:

- **Backend** (`backend/` FastAPI service)
- **Agent Core** (`agent/` reasoning engine, ML pipelines, workers)
- **Frontend** (`frontend/` Next.js application, API routes, edge functions)
- **Supporting Services** (scripts, schedulers, ETL jobs, integration tests)
- **Infrastructure & Deployment** (Docker, Kubernetes, CI/CD pipelines, cloud resources)

---

## Functional Requirements

1. **Structured Output**  
   Logs must be structured (JSON) with consistent fields to enable filtering and analytics.

2. **Severity Levels**  
   Support `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

3. **Correlation IDs**  
   Every request or job should carry `correlation_id` and `request_id` to correlate events between services.

4. **Contextual Metadata**  
   Include service name, environment, version, user/session identifiers (if applicable), and deployment identifiers.

5. **Error Capture**  
   Automatically log uncaught exceptions and rejected promises (frontend) / unhandled exceptions (backend/agent).

6. **Startup Clearing**  
   At service bootstrap, rotate or delete prior log files to ensure a fresh log stream, unless retention policies require archival.

7. **Retention & Rotation**  
   Default to 7-day retention in development; production retention configured via environment.

8. **Transport**  
   Support writing to STDOUT, local files, and remote log collectors (e.g., ELK/EFK, Loki, CloudWatch).

9. **Privacy Compliance**  
   Prevent logging of secrets, tokens, PII, or sensitive trading strategies in raw form.

---

## Architecture

### 1. Log Emitters

| Service      | Logger Library        | Output                           |
|--------------|-----------------------|----------------------------------|
| Backend      | `structlog` + `logging` | JSON to STDOUT & rotating file   |
| Agent Core   | `structlog` / `loguru` | JSON to STDOUT & rotating file   |
| Frontend     | `pino` or `winston`    | JSON to STDOUT; browser console  |
| Scripts/CLI  | `structlog`            | JSON to STDOUT & optional file   |

### 2. Log Processing Pipeline

```
Service Emitters → Local Rotating Files → (optional) Forwarder → Central Collector → Storage/Search → Alerts/Dashboards
```

### 3. Storage Options

- **Development**: Local `logs/` directory with daily rotation (`logs/backend/YYYY-MM-DD.log`).
- **Production**: Centralized stack (e.g., Loki + Grafana, Elastic stack, Datadog) with TLS.

### 4. Version Control & Generated Artefacts

- **Logs are not version-controlled**: the `logs/` directory and individual `*.log` files are ignored via `.gitignore` and must never be committed.
- **Run-scoped only**: log files are treated as per-run diagnostics that are cleared or rotated between sessions (see [Startup Clearing Procedure](#startup-clearing-procedure)).
- **Diagnostic markdown reports**: time-stamped log-analysis or audit snapshots are kept under `docs/` (usually `docs/archive/`) as examples; they can be regenerated or pruned without affecting application behaviour.

### 5. Clearing Strategy

- On service startup, clear or archive previous log files:
  - Archive or delete previous log files (can be done via startup scripts or manually).
  - Register session metadata (`session_id`, `start_time`, `commit_sha`).
  - Emit a `system.startup` log event with summary of previous session (if archived).
  - Note: Log clearing functionality should be implemented in startup scripts or service initialization code.

---

## Log Schema

All JSON log entries must include the following base fields:

| Field             | Type    | Description                                   |
|-------------------|---------|-----------------------------------------------|
| `timestamp`       | ISO8601 | Event time                                    |
| `level`           | String  | Severity (`INFO`, `ERROR`, etc.)              |
| `message`         | String  | Human-readable description                    |
| `service`         | String  | Emitting service (`backend`, `agent`, etc.)   |
| `component`       | String  | Logical component or module                   |
| `correlation_id`  | String  | Correlates related events                     |
| `request_id`      | String  | HTTP request identifier (if applicable)       |
| `session_id`      | String  | Service run identifier (new each start)       |
| `environment`     | String  | `local`, `staging`, `production`, etc.        |
| `version`         | String  | Git commit or semantic version                |
| `details`         | Object  | Additional metadata                           |

**Error Logs** must also include:

- `error.type`
- `error.message`
- `error.stack` (redacted in production if necessary)
- `error.code` (if defined)

**Sample Entries**

```json
{
  "timestamp": "2025-01-12T10:30:02.415Z",
  "level": "INFO",
  "service": "backend",
  "component": "routes.health.get_health",
  "message": "health_check_passed",
  "correlation_id": "req_health_1741",
  "session_id": "sess_01HV6Z8P8ZN8TEFQH5MZ9YV24S",
  "environment": "local",
  "version": "a1b2c3d",
  "details": {
    "health_score": 0.97,
    "latency_ms": 42
  }
}
```

```json
{
  "timestamp": "2025-01-12T10:31:44.982Z",
  "level": "ERROR",
  "service": "agent",
  "component": "models.registry",
  "message": "model_prediction_failed",
  "correlation_id": "req_predict_2743",
  "session_id": "sess_01HV6Z8P8ZN8TEFQH5MZ9YV24S",
  "environment": "local",
  "version": "a1b2c3d",
  "details": {
    "model": "xgboost_BTCUSD_1h",
    "retry": 1
  },
  "error": {
    "type": "TimeoutError",
    "message": "model exceeded 750ms execution limit",
    "code": "MODEL_TIMEOUT"
  }
}
```

Use the info and error samples when constructing log ingestion tests or validating dashboards.

---

## Service Integration

### Backend (FastAPI)

1. **Logging Library**  
   Configure `structlog` with `logging` bridge in `backend/core/logging.py`.

2. **Error Log Aggregation**  
   Errors are automatically logged to dedicated files:
   - `logs/backend/errors.log` - All ERROR and CRITICAL level logs
   - `logs/backend/warnings.log` - All WARNING level logs
   - `logs/backend/backend.log` - All logs (main log file)

3. **Uvicorn Integration**  
   Intercept Uvicorn access logs and format them to JSON.

4. **Middleware**  
   Add `LoggingMiddleware` to inject `request_id` per request and record start/end events.

5. **Exception Handlers**  
   Global exception handler logs `ERROR` level entries with full context:
   - Request ID, path, method
   - Error type and message
   - Stack traces
   - Client IP and user agent

6. **Startup Clearing**  
   Clear or archive previous log files before app start. Log files are automatically archived on startup. A new `session_id` is generated for each service run.

7. **Graceful Shutdown**  
   Emit `system.shutdown` log with request statistics and error counts.

### Agent Core

1. **Logger Setup**  
   Initialize structured logger in `agent/core/intelligent_agent.py` using `agent/core/logging_utils.py`.

2. **Error Log Aggregation**  
   Errors are automatically logged to dedicated files:
   - `logs/agent/errors.log` - All ERROR and CRITICAL level logs
   - `logs/agent/warnings.log` - All WARNING level logs
   - `logs/agent/agent.log` - All logs (main log file)

3. **Global Exception Handlers**  
   Global exception handlers in `agent/core/exception_handlers.py` catch:
   - Unhandled synchronous exceptions (`sys.excepthook`)
   - Unhandled async exceptions (`asyncio.set_exception_handler`)
   - Thread exceptions (`threading.excepthook`)

4. **Error Metrics Tracking**  
   Error metrics are automatically tracked in `agent/core/error_metrics.py`:
   - Error counts by type and component
   - Error rates over time windows
   - Periodic error summary logs (every 5 minutes)

5. **State Machine Events**  
   Log every state transition (`state`, `prev_state`, `reason`).

6. **Model Inference Errors**  
   Wrap model calls to capture inference errors, timeouts, degraded performance.

7. **Background Tasks**  
   Ensure async tasks propagate correlation IDs and log outcomes.

8. **Startup/Shutdown Events**  
   - Emit `system.startup` event with session_id, commit SHA, environment, model versions
   - Emit `system.shutdown` event with runtime statistics, error counts, graceful shutdown status

### Frontend (Next.js)

1. **Server-side Logging**  
   Use `pino` (or `winston`) in API routes and Next.js middleware for structured logs.

2. **Client-side Logging**  
   Wrap `console.error` to forward critical errors to a central endpoint (`/api/log`).

3. **Hydration & Runtime Errors**  
   Log to remote logging service with sanitized payloads; include user session ID.

4. **Startup Clearing**  
   During development server start (`next dev`), purge `logs/frontend/` and emit `frontend.startup`.

### Infrastructure & Scripts

1. **Deployment Pipelines**  
   Pipeline scripts should push deployment logs to `logs/deployments/YYYY-MM-DD.log`.

2. **Scheduled Jobs**  
   Each job execution logs start and completion events with job ID.

3. **Test Suites**  
   Integration tests log to `logs/tests/` with correlation IDs referencing build number.

---

## Startup Clearing Procedure

1. **Define log directories** per service (`logs/backend`, `logs/agent`, etc.).
2. **On process start**, run:
   - `archive_previous_logs()` (move to `archive/YYYYMMDD_HHMM/`)
   - or `delete_previous_logs()` (configurable via `LOG_ARCHIVE_MODE`).
3. **Generate new session ID** (`uuid4` or ULID).
4. **Emit startup log**:

```json
{
  "timestamp": "2025-01-12T08:00:00Z",
  "level": "INFO",
  "service": "backend",
  "message": "system.startup",
  "session_id": "sess_01HV...",
  "details": {
    "environment": "development",
    "version": "a1b2c3d",
    "archived_logs": 3
  }
}
```

5. **Update health checks** to include logging status (last startup event, writable directories).

---

## Configuration & Environment Variables

| Variable                    | Description                                     | Default             |
|----------------------------|-------------------------------------------------|---------------------|
| `LOG_LEVEL`                | Global minimum severity (`INFO`, `DEBUG`, etc.) | `INFO`              |
| `LOG_FORMAT`               | `json` (default) or `text`                      | `json`              |
| `LOG_DIR`                  | Base path for log files                         | `./logs`            |
| `LOG_RETENTION_DAYS`       | Days to retain logs locally                     | `7`                 |
| `LOG_ARCHIVE_MODE`         | `delete` or `archive` prior logs                | `archive`           |
| `LOG_FORWARDING_ENABLED`   | Enable remote collector forwarding              | `false`             |
| `LOG_FORWARDING_ENDPOINT`  | Remote collector URL                            | -                   |
| `LOG_SAMPLING_RATE`        | Fraction of DEBUG logs to retain (0-1)          | `1.0`               |
| `LOG_INCLUDE_STACKTRACE`   | Include stack traces in production (`true/false`)| `false`             |
| `LOG_SESSION_ID`           | Optional override for session identifier        | Generated per start |

---

## Observability Integration

1. **Metrics Correlation**  
   Emit log-derived metrics (error counts, latency buckets) to Prometheus/Grafana.\n
2. **Alerting**  
   - `ERROR` rate > threshold → PagerDuty / Slack alert.
   - Missing startup log within deployment window → deployment failure alert.
3. **Dashboards**  
   Provide visualizations for error trends, slow requests, degraded states.
4. **Tracing**  
   Integrate with OpenTelemetry to enrich traces with log events.

---

## Operational Procedures

### Daily
- Verify `system.startup` events exist for every service.
- Check that log directories are cleared or archived.
- Review `ERROR` and `CRITICAL` logs for remediation.

### Weekly
- Validate retention policies and disk usage.
- Audit for any secrets or sensitive data in logs.
- Rotate log encryption keys if applicable.

### Incident Response
- Use correlation IDs to gather related log entries.
- Export relevant logs to incident ticket with timestamps and context.
- After resolution, document lessons learned in `postmortems/`.

---

## Error Analysis Tools

The project includes tools for analyzing error logs and identifying issues:

### 1. Error Analysis Script (`tools/commands/analyze-errors.py`)

Generates comprehensive error reports from log files:

```bash
# Analyze default log files
python tools/commands/analyze-errors.py

# Analyze specific log files
python tools/commands/analyze-errors.py --log-file logs/agent/errors.log --log-file logs/backend/errors.log

# Save report to file
python tools/commands/analyze-errors.py --output logs/error/analysis-report.json
```

**Report includes:**
- Error counts by type and component
- Most frequent errors
- Errors by component
- Recent critical errors
- Runtime error metrics (if available)

### 2. Error Viewer Script (`tools/commands/view-errors.py`)

Interactive error log viewer with filtering:

```bash
# View recent errors
python tools/commands/view-errors.py --tail 50

# Filter by component
python tools/commands/view-errors.py --component execution_module

# Filter by error type
python tools/commands/view-errors.py --error-type TimeoutError

# Filter by log level
python tools/commands/view-errors.py --level ERROR

# Show full entry details
python tools/commands/view-errors.py --full --tail 10
```

**Features:**
- Color-coded output by severity
- Filter by component, error type, log level
- Show recent entries (tail)
- Full entry details option

### 3. Error Metrics

Runtime error metrics are automatically tracked and available via:

```python
from agent.core.error_metrics import get_error_summary

summary = get_error_summary()
print(f"Total errors: {summary.total_errors}")
print(f"Error rate: {summary.error_rate_per_minute} errors/minute")
```

Error summaries are also logged periodically (every 5 minutes) with the event `error_summary_periodic`.

## Testing the Logging System

1. **Unit Tests**
   - Mock loggers and assert structured output.
   - Verify startup clearing logic deletes/archives files.
   - Test error metrics tracking.

2. **Integration Tests**
   - Simulate an error in each service and assert log entry with correct schema.
   - Validate correlation IDs propagate across backend → agent → frontend.
   - Verify errors are written to dedicated error log files.

3. **Performance Tests**
   - Ensure logging does not exceed 5% CPU overhead under load.
   - Stress test log rotation under high write volume.

4. **Chaos Tests**
   - Force disk full scenarios; verify graceful degradation.
   - Simulate logger failure and ensure service continues running with fallback.

5. **Error Analysis Tests**
   - Verify error analysis tools can parse log files correctly.
   - Test error metrics aggregation.

---

## Security & Compliance

- Mask or hash PII (user IDs, IP addresses) when required.
- Avoid logging secrets, tokens, or raw trading strategies.
- Use transport encryption (TLS) for remote log forwarding.
- Apply RBAC to logging dashboards and storage.
- Implement log tamper detection via signatures or append-only storage if regulated.

---

## Implementation Roadmap

1. **Phase 0 – Preparation**
   - Create logging module stubs in each service.
   - Define shared logging schema package (`logging_schema.py` / `logging.ts`).

2. **Phase 1 – Basic Structured Logging**
   - Implement structured logging in backend and agent.
   - Add startup clearing logic and session IDs.

3. **Phase 2 – Frontend & Scripting**
   - Instrument Next.js API routes and client error forwarding.
   - Integrate scripts and scheduled jobs.

4. **Phase 3 – Observability Integration**
   - Connect to central log collector.
   - Build Grafana dashboards and alerts.

5. **Phase 4 – Compliance & Hardening**
   - Implement retention, redaction, and security controls.
   - Add automated logging audits in CI.

---

## References

- [Backend Documentation](06-backend.md) – update logging section with implementation specifics.
- [Deployment Documentation](10-deployment.md) – include logging setup and verification steps.
- [Project Rules](14-project-rules.md) – enforce logging standards in code reviews.
- [Build Guide](11-build-guide.md) – ensure scripts call log bootstrapper during setup.

---

## Change Log

| Date       | Version | Description                              |
|------------|---------|------------------------------------------|
| 2025-01-12 | 1.0.0   | Initial logging system documentation     |
| 2025-01-XX | 2.0.0   | Comprehensive error logging system:
|            |         | - Dedicated error/warning log files
|            |         | - Global exception handlers
|            |         | - Error metrics tracking
|            |         | - Error analysis tools (analyze-errors.py, view-errors.py)
|            |         | - Enhanced error context logging


