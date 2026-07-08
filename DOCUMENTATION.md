# JackSparrow Documentation

> **AI-Powered Trading Agent for Delta Exchange India Paper Trading**

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

All maintained project documentation lives under **`docs/01-architecture.md` through `docs/15-audit-report.md`**. Use this file as the index only.

---

## Documentation index (canonical)

| # | Document | Topics |
|---|----------|--------|
| 01 | [Architecture](docs/01-architecture.md) | System design, tiers, communication, startup |
| 02 | [MCP layer](docs/02-mcp-layer.md) | Feature / model / reasoning protocols |
| 03 | [ML models](docs/03-ml-models.md) | **IC / NO-ML** (`metadata_ic.json`, `RuleBasedIntelligenceNode`), v43 feature contract, archived XGBoost bundles, Delta **REST vs WSS** hosts, Docker **`MODEL_DIR` / `WEBSOCKET_URL`**, optional **adaptive retrain** (v15 parquet only) |
| 04 | [Features](docs/04-features.md) | Product capabilities, signal triggers |
| 05 | [Logic & reasoning](docs/05-logic-reasoning.md) | Six-step chain, consensus, vector memory, **deterministic self-awareness** (introspection / outcome backfill / advisory reflection) |
| 06 | [Backend](docs/06-backend.md) | FastAPI, REST, WebSocket contract, services |
| 07 | [Frontend](docs/07-frontend.md) | Next.js, `useTradingData`, WebSocket UI, portfolio ROE % (`portfolioMetrics`) |
| 08 | [File structure](docs/08-file-structure.md) | Repository layout |
| 09 | [UI/UX](docs/09-ui-ux.md) | Dashboard design, accessibility |
| 10 | [Deployment](docs/10-deployment.md) | Env, Docker (production vs dev overlay, optional Qdrant), DB, health/Redis metrics, hot reload |
| 11 | [Build guide](docs/11-build-guide.md) | End-to-end setup, tests, commands |
| 12 | [Logging](docs/12-logging.md) | Structured logging, container triage, `trading_entry_rejected` reasons, paper/signal audit (IST ledger + `live_audit.md`), risk-approval reconciliation CLI |
| 13 | [Debugging](docs/13-debugging.md) | Diagnostics, Windows/local issues |
| 14 | [Project rules](docs/14-project-rules.md) | Standards and contribution |
| 15 | [Audit report](docs/15-audit-report.md) | Audit workflow, gaps, remediation, ML confidence checks |
| 16 | [v43 trade execution runbook](docs/v43_trade_execution_runbook.md) | v43 **signal gate** tuning (IC + archived ML), metrics, rollback, log analysis |
| — | [Rule-based decision engine](docs/rule-based-decision-engine.md) | FSM + structural gates, shadow rollout, `DECISION_ENGINE_MODE`, UI payloads |
| — | [Canonical events](docs/canonical_events.md) | Event-bus wiring and `DECISION_READY` payload fields |
| — | [Entry quality and lifecycle](docs/entry-quality-and-lifecycle.md) | Quality-first entry scoring, Gate 5 economics (`MIN_EDGE_COST_RATIO=0.75`), ADX chop filter on v43, TLE + forecast adapter, learning loop |
| — | [Trade lifecycle engine](reference/trade-lifecycle-engine.md) | Position intelligence, expectation forecast adapter, exit engine, promotion replay |
| — | [Trading persistence model](reference/trading-persistence-model.md) | Testnet three-layer model, snapshot schema v1, analytics tables, Docker notes |
| — | [Trade Intelligence Snapshot v2](reference/trade-intelligence-snapshot-v2.md) | Decision events, causality graph, MFE/MAE, reject labels, shadow rollout |
| — | [Cognitive architecture](reference/cognitive-architecture.md) | DecisionContext v3, expectation/memory/scenario, strategy selector + scorer, shadow rollout |

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
| Docker runtime ports & paths | [Deployment – Docker runtime topology](docs/10-deployment.md#docker-runtime-topology-reference) (agent 8002/8003 internal in production; dev overlay exposes host ports) |
| Operational health (market data, latency) | [Deployment – Docker runtime topology](docs/10-deployment.md#docker-runtime-topology-reference), [Backend – Health](docs/06-backend.md#health--status) |
| Deprecated REST predict/execute | [Backend – Trading operations](docs/06-backend.md#trading-operations), `ENABLE_DEPRECATED_REST_TRADING` in `.env.example` |
| Model bundles & `MODEL_DIR` | [ML models – IC discovery](docs/03-ml-models.md#runtime-discovery-no-ml-intelligence-component), [Bundle profiles](docs/03-ml-models.md#bundle-profiles-and-docker-defaults) |
| Delta WebSocket (testnet) | [Deployment – Agent env](docs/10-deployment.md#agent-environment-variables), `.env.example` (`socket-ind` host, `key-auth`) |
| Entry lot sizing (60% portfolio, fixed leverage) | [Logic & reasoning – Entry lot sizing](docs/05-logic-reasoning.md#entry-lot-sizing-portfolio-fraction), `.env.example` (`ENTRY_PORTFOLIO_MARGIN_FRACTION`, `PORTFOLIO_FRACTION_LOT_SIZING`) |
| Adaptive drift / warm-start retrain (v15) | [ML models – Runtime adaptive retrain](docs/03-ml-models.md#runtime-adaptive-retrain-v15-pipeline-optional), [Deployment – Agent env](docs/10-deployment.md#agent-environment-variables), [.env.example](.env.example) |
| Trading Signal hero metrics (policy / edge / margin / score) | [Frontend – signal fields](docs/07-frontend.md#v15--v43-signal-fields-optional), [Logic – Dashboard confidence](docs/05-logic-reasoning.md#dashboard-confidence-semantics-policy-vs-reasoning-vs-display), [Backend – signal payload](docs/06-backend.md#websocket-protocol) |
| WebSocket message shape | [Backend – WebSocket](docs/06-backend.md#websocket-protocol), [Frontend – WebSocket](docs/07-frontend.md#websocket-integration) |
| Latest signal REST hydrate | [Backend – GET `/api/v1/signal/latest`](docs/06-backend.md#get-apiv1signallatest), [Frontend – `useTradingData`](docs/07-frontend.md#unified-dashboard-state-usetradingdata) |
| No trades / stale UI signal | [Debugging – No trades](docs/13-debugging.md#no-trades-executed), [Logging – `trading_entry_rejected`](docs/12-logging.md#6-trading-handler-events-agenteventshandlerstrading_handlerpy) |
| Self-awareness flags & telemetry | [Logic & reasoning – Self-awareness](docs/05-logic-reasoning.md#deterministic-self-awareness), [Canonical events](docs/canonical_events.md), `.env.example` |
| Rule-based FSM rollout / shadow logs | [Rule-based decision engine](docs/rule-based-decision-engine.md), `tools/analyze_agent_logs.py`, [Deployment – Agent env](docs/10-deployment.md#agent-environment-variables) |
| Cognitive layer (shadow `decision_context_v3`) | [Cognitive architecture](reference/cognitive-architecture.md), [Rule-based decision engine – Cognition](docs/rule-based-decision-engine.md#cognitive-layer-decisioncontext-v3), `pytest tests/unit/cognition/`, `run_scenario_tests.py --cognition` |
| Entry quality / July replay | [Entry quality and lifecycle](docs/entry-quality-and-lifecycle.md), `tests/integration/test_july2_telemetry_replay.py`, `tools/commands/monte_carlo_replay.py` |
| TLE promotion / EV exit replay | [Trade lifecycle engine](reference/trade-lifecycle-engine.md), `tools/commands/run_tle_investigation.py` |
| Trade snapshot analytics / optimization | [Trading persistence model](reference/trading-persistence-model.md), [Snapshot v2](reference/trade-intelligence-snapshot-v2.md), `tools/commands/trade_analytics.py`, [Backend – Analytics API](docs/06-backend.md#analytics-rest-api) |
| Snapshot v2 shadow rollout / decision events | [Trade Intelligence Snapshot v2](reference/trade-intelligence-snapshot-v2.md), [Deployment – Alembic](docs/10-deployment.md#alembic-migrations), `tools/commands/phase_readiness_gate.py`, `tools/commands/label_entry_decisions.py` |
| Docker rebuild / redeploy | [Deployment – Common operations](docs/10-deployment.md#common-operations), `docker compose build --pull` + `up -d --force-recreate` |
| Alembic / schema drift after upgrade | [Deployment – Alembic migrations](docs/10-deployment.md#alembic-migrations), `backend/migrations/README.md` |
| Troubleshooting | [Debugging](docs/13-debugging.md), [Deployment – Troubleshooting](docs/10-deployment.md#troubleshooting) |
| AI signal / paper trade audit (IST ledger + markdown + structlog) | [reference/ai-signal-action-audit-log.md](reference/ai-signal-action-audit-log.md), [Logging – Audit journal](docs/12-logging.md#ai-signal-and-action-audit-journal), [Deployment – host log paths](docs/10-deployment.md#common-operations) |

---

## Contributing

When you change behavior, update the **numbered** doc that owns that topic. Do not add new standalone markdown under `docs/` except the `01`–`15` set (see [Project rules](docs/14-project-rules.md)).

**Last updated**: 2026-07-04 — Trade Intelligence Snapshot v2 (decision events, MFE/MAE, reject labels, denorm analytics API), migrations 004–006, shadow rollout env flags.
