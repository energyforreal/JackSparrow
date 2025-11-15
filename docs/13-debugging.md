# Debugging & Error Handling Guide

## Overview

This guide explains how to diagnose, reproduce, and resolve issues while the JackSparrow trading agent is under active development. It complements [Logging Documentation](12-logging.md) by describing **how** to exercise the logging system, enable debugging modes, and interpret log output across services.

---

## Table of Contents

- [Overview](#overview)
- [Core Principles](#core-principles)
- [Environment Setup Checklist](#environment-setup-checklist)
- [Service Debug Modes](#service-debug-modes)
  - [Backend (FastAPI)](#backend-fastapi)
  - [Agent Core](#agent-core)
  - [Frontend (Next.js)](#frontend-nextjs)
  - [Schedulers & Scripts](#schedulers--scripts)
- [Working with Logs](#working-with-logs)
  - [Log Locations](#log-locations)
  - [Inspecting Logs](#inspecting-logs)
  - [Troubleshooting with Log Context](#troubleshooting-with-log-context)
- [Common Workflows](#common-workflows)
  - [Reproducing API Failures](#reproducing-api-failures)
  - [Debugging Model Inference Issues](#debugging-model-inference-issues)
  - [Chasing Frontend Runtime Errors](#chasing-frontend-runtime-errors)
- [Incident Response Playbook](#incident-response-playbook)
- [Tooling & Integrations](#tooling--integrations)
- [Best Practices](#best-practices)
- [References](#references)
- [Change Log](#change-log)

---

## Core Principles

1. **Reproducibility first** – capture minimal steps, inputs, and environment variables before diving into the fix.
2. **Structured evidence** – rely on JSON logs (see [Logging Documentation](12-logging.md)) and correlation IDs to stitch together cross-service behaviour.
3. **Fail fast, fail loud** – keep `DEBUG` level enabled in development unless profiling performance; warnings and errors must never be ignored.
4. **Automate verification** – whenever possible, add regression tests or ad-hoc scripts to confirm that a bug is fixed and remains fixed.

---

## Environment Setup Checklist

Before debugging:

- Pull the latest code and confirm the branch matches the reported issue.
- Export or populate the `.env` file according to [Deployment Documentation](10-deployment.md#environment-variables-reference).
- Run `start` (see [Build Guide](11-build-guide.md#project-commands)) to launch all services with fresh session IDs.
- Ensure the `logs/` directory is writable; the startup bootstrapper should purge old logs per [Logging Documentation](12-logging.md#startup-clearing-procedure).
- Confirm monitoring dashboards (Grafana, etc.) are pointed to the correct environment if using remote observability.

---

## Service Debug Modes

### Backend (FastAPI)

- Set `LOG_LEVEL=DEBUG` in `.env` to increase verbosity.
- Use Uvicorn’s reload server for local dev: `uvicorn backend.api.main:app --reload`.
- Launch with Python debugging hooks when needed:

```shell
uvicorn backend.api.main:app --reload --log-level debug
```

- Attach a debugger (VS Code, PyCharm) to the FastAPI process; breakpoints in route handlers and services are honoured when `--reload` is active.
- All exceptions are captured by custom handlers and written as `ERROR` events with stack traces (see [Logging Documentation](12-logging.md#service-integration)).

### Agent Core

- Use `LOG_LEVEL=DEBUG` and `LOG_AGENT_TRACE=1` (if available) to surface state transitions.
- Start the agent process manually to step through execution:

```shell
python -m agent.core.intelligent_agent --debug
```

- Model inference wrappers log `model_prediction_failed` events; inspect `details` for model identifiers and retry state.
- When profiling asynchronous workers, enable structured logging for Celery/async tasks and propagate correlation IDs.

### Frontend (Next.js)

- Run `next dev` to enable hot reload and source-mapped stack traces:

```shell
pnpm dev
```

- Activate server-side logging by setting `LOG_LEVEL=debug` in `.env.local` or `.env` and confirm the `pino`/`winston` transport writes into `logs/frontend/`.
- Client-side errors are mirrored to `/api/log`; inspect both browser console and server logs (with correlation IDs) for full context.
- Use the Next.js debug overlay to inspect component stack traces; replicate render errors with React Developer Tools.

### Schedulers & Scripts

- CLI tools inherit the project logging configuration. Run commands with `--debug` flags when provided, e.g.:

```shell
python scripts/replay_trades.py --debug
```

- Cron or workflow executions write to `logs/tests/` or `logs/deployments/`; include job IDs in your incident notes.

---

## Working with Logs

### Log Locations

| Service             | Path                            | Notes |
|---------------------|---------------------------------|-------|
| Backend             | `logs/backend/YYYY-MM-DD.log`   | Rotated daily; contains API access & app logs |
| Agent Core          | `logs/agent/YYYY-MM-DD.log`     | Includes state transitions and model events |
| Frontend            | `logs/frontend/YYYY-MM-DD.log`  | Next.js server logs plus forwarded client errors |
| Schedulers/Scripts  | `logs/tests/` / `logs/deployments/` | Named per job run |

### Inspecting Logs

- Follow the fresh-start rule: each service emits a `system.startup` entry with the new `session_id`.
- Filter locally using `jq`, `rg`, or `python -m json.tool`. Example:

```shell
jq 'select(.level == "ERROR")' logs/backend/2025-11-13.log
```

- Correlate cross-service events by matching `correlation_id` (per request) and `session_id` (per run).
- Use observability dashboards (Grafana, ELK, Loki) to aggregate trends; alerts trigger when error thresholds are crossed.

### Troubleshooting with Log Context

1. Identify the failing service via `service` field.
2. Inspect `error.type`, `error.message`, and `details` for hints.
3. Trace any upstream dependencies (DB, external APIs) recorded in `details`.
4. Note the `version` (`git` SHA) to ensure logs map to the same code you are testing.
5. When sharing findings, include the raw JSON snippet and correlation IDs.

---

## Common Workflows

### Reproducing API Failures

1. Obtain the HTTP request payload (REST, WebSocket) from logs or client reports.
2. Use `start` to relaunch services, ensuring the log bootstrapper clears old entries.
3. Replay the request with `httpie`, `curl`, or integration tests.
4. Watch backend logs for `ERROR` entries; confirm FastAPI middleware appended correlation IDs.
5. Set breakpoints in the relevant route/service if the failure persists.

### Debugging Model Inference Issues

1. Locate `model_prediction_failed` entries in `logs/agent/`.
2. Review `details.model`, `details.retry`, and performance metrics.
3. Manually run the model with stored inputs to reproduce (scripts in `scripts/` directory).
4. Enable verbose ML logging (`MODEL_DEBUG=1`) if the pipeline supports it.
5. Update regression notebooks or tests to prevent the issue from recurring.

### Chasing Frontend Runtime Errors

1. Reproduce using the same browser/viewport; capture console output.
2. Verify `/api/log` is receiving forwarded errors and check `logs/frontend/`.
3. Use React Profiler/DevTools to inspect component state leading to the error.
4. If a backend dependency is suspected, use the shared `correlation_id` to trace backend logs.
5. Fixes should include unit or integration tests plus manual verification in dev mode.

---

## Incident Response Playbook

1. **Detect** – Monitor alerts or `ERROR` spikes in remote dashboards.
2. **Triage** – Confirm impact, affected services, and recent deployments (check `system.startup` events).
3. **Contain** – Roll back the change or disable the offending feature flag if required.
4. **Diagnose** – Collect logs, correlation IDs, and reproduction steps. Escalate with a shared incident doc.
5. **Resolve** – Apply the fix, deploy, and verify using the same log paths.
6. **Document** – Add notes to `postmortems/` and update regression tests.

---

## Tooling & Integrations

- **Debugger Attachments**: VS Code launch configs (`.vscode/launch.json`) should target backend and agent processes.
- **Tracing**: OpenTelemetry (if configured) enriches spans with log events; inspect via Grafana Tempo or Jaeger.
- **Profiling**: Use `py-spy`, `cProfile`, or `node --inspect` for performance-related bugs; remember to restore normal log levels after profiling.
- **Static Analysis**: Run `ruff`, `mypy`, `eslint`, and unit tests before shipping fixes to catch regressions early.

---

## Best Practices

- Keep `DEBUG` logging scoped: elevate to `INFO` or `ERROR` once the issue is resolved.
- Redact secrets before sharing logs externally; follow the privacy guidelines in [Logging Documentation](12-logging.md#security--compliance).
- Automate log review with scripts—use the `error` command (see [Build Guide](11-build-guide.md#project-commands) or [Deployment Documentation](10-deployment.md#operations--maintenance-commands)) for quick inspections.
- When filing bug reports, include: service, environment, correlation ID, reproduction steps, and observed vs expected behaviour.
- After fixes, verify both locally and via CI pipelines; attach relevant log excerpts to pull requests for reviewer context.

---

## References

- [Logging Documentation](12-logging.md) – Log schema, bootstrapper, and retention policies.
- [Backend Documentation](06-backend.md) – FastAPI operations and monitoring commands.
- [Frontend Documentation](07-frontend.md) – Next.js development workflows and error handling.
- [Deployment Documentation](10-deployment.md) – Environment setup, `.env` variables, and project commands.
- `DOCUMENTATION.md` – Central index for documentation and command references.

---

## Change Log

| Date       | Version | Description                     |
|------------|---------|---------------------------------|
| 2025-11-13 | 1.0.0   | Initial debugging guide created |
