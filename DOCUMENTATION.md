# JackSparrow Documentation

> **AI-Powered Trading Agent for Delta Exchange India Testnet**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

All maintained project documentation lives under **`docs/01-architecture.md` through `docs/15-audit-report.md`**. Use this file as the index only.

---

## Documentation index (canonical)

| # | Document | Topics |
|---|----------|--------|
| 01 | [Architecture](docs/01-architecture.md) | System design, tiers, communication, startup |
| 02 | [MCP layer](docs/02-mcp-layer.md) | Feature / model protocols, transformer orchestration |
| 03 | [ML models](docs/03-ml-models.md) | **Transformer ONNX** (`metadata_transformer.json`, Colab export), `TRANSFORMER_*` env vars, Docker `MODEL_DIR` |
| 04 | [Features](docs/04-features.md) | Product capabilities, signal triggers |
| 05 | [Logic & reasoning](docs/05-logic-reasoning.md) | Transformer decision path, vector memory, **deterministic self-awareness** |
| 06 | [Backend](docs/06-backend.md) | FastAPI, REST, WebSocket contract, services |
| 07 | [Frontend](docs/07-frontend.md) | Next.js, `useTradingData`, WebSocket UI, portfolio ROE % |
| 08 | [File structure](docs/08-file-structure.md) | Repository layout |
| 09 | [UI/UX](docs/09-ui-ux.md) | Dashboard design, accessibility |
| 10 | [Deployment](docs/10-deployment.md) | Env, Docker, DB, health, testnet-only validation |
| 11 | [Build guide](docs/11-build-guide.md) | End-to-end setup, transformer tests, commands |
| 12 | [Logging](docs/12-logging.md) | Structured logging, audit journal, `trading_entry_rejected` |
| 13 | [Debugging](docs/13-debugging.md) | Diagnostics, signal recovery CLI, Windows/local issues |
| 14 | [Project rules](docs/14-project-rules.md) | Standards and contribution |
| 15 | [Audit report](docs/15-audit-report.md) | Audit workflow, gaps, remediation |

---

## Suggested reading order

1. [Architecture](docs/01-architecture.md) — big picture  
2. [MCP layer](docs/02-mcp-layer.md) — how components speak  
3. [ML models](docs/03-ml-models.md) + [Logic & reasoning](docs/05-logic-reasoning.md) — signals and decisions  
4. [Deployment](docs/10-deployment.md) + [Build guide](docs/11-build-guide.md) — run the stack  
5. [Backend](docs/06-backend.md) / [Frontend](docs/07-frontend.md) — integration details  

---

## Quick commands

| Goal | Where to look |
|------|----------------|
| Start / validate stack | [Build guide – Project commands](docs/11-build-guide.md#project-commands), [Deployment – Validation](docs/10-deployment.md#validation-and-monitoring-commands) |
| Docker runtime ports & paths | [Deployment – Docker runtime topology](docs/10-deployment.md#docker-runtime-topology-reference) |
| Transformer bundle & `MODEL_DIR` | [ML models – Runtime discovery](docs/03-ml-models.md#runtime-discovery-transformer-onnx) |
| Delta WebSocket (testnet) | [Deployment – Agent env](docs/10-deployment.md#agent-environment-variables), `.env.example` |
| Entry lot sizing | [Logic & reasoning – Entry lot sizing](docs/05-logic-reasoning.md#entry-lot-sizing-portfolio-fraction) |
| WebSocket message shape | [Backend – WebSocket](docs/06-backend.md#websocket-protocol), [Frontend – WebSocket](docs/07-frontend.md#websocket-integration) |
| Latest signal REST hydrate | [Backend – GET `/api/v1/signal/latest`](docs/06-backend.md#get-apiv1signallatest) |
| No trades / stale UI signal | [Debugging – No trades](docs/13-debugging.md#no-trades-executed) |
| Self-awareness telemetry | [Logic & reasoning – Self-awareness](docs/05-logic-reasoning.md#deterministic-self-awareness) |
| Signal recovery CLI | [Debugging](docs/13-debugging.md) (`scripts/signal_recovery/run.py`) |
| Troubleshooting | [Debugging](docs/13-debugging.md), [Deployment – Troubleshooting](docs/10-deployment.md#troubleshooting) |

---

## Contributing

When you change behavior, update the **numbered** doc that owns that topic. Do not add new standalone markdown under `docs/` except the `01`–`15` set (see [Project rules](docs/14-project-rules.md)).

**Last updated**: 2026-08-01 — Transformers branch: ONNX transformer runtime, testnet-only docs, removed IC/v43 runbooks from index.
