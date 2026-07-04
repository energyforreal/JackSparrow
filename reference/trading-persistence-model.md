# Trading persistence model (JackSparrow / Trading Agent 2)

## Three-layer analytics model (testnet-first)

| Layer | Role | Primary store |
|-------|------|----------------|
| **Execution** | Authoritative fills, open legs, brackets | Delta Exchange (testnet) |
| **Analytics warehouse** | Decision context, funnel, cohort rollups | PostgreSQL: `trade_outcomes`, `entry_decisions`, `analytics_rollups` |
| **Hot UI cache** | Recent closed trades for dashboard | Redis + `data/agent_closed_trades.jsonl` (archived when capped) |

On **testnet**, PostgreSQL does not mirror every exchange fill as `trades`/`positions` rows (`trade_persistence_service` skips with `testnet_exchange_ledger`). **`trade_outcomes`** plus full **decision snapshots** in `metadata` JSONB are the optimization target.

---

## Testnet (`TRADING_MODE=testnet`)

- **Authoritative ledger:** Delta Exchange margined positions and open orders.
- **PostgreSQL:** Trade/position rows are **not** written for testnet fills (`trade_persistence_service` skips with `testnet_exchange_ledger`).
- **Analytics:** `trade_outcomes`, `entry_decisions`, and `analytics_rollups` are written fire-and-forget from the agent (`agent/persistence/db_writes.py`).
- **On startup:** `position_restore` from DB is optional; **exchange reconcile** (`EXCHANGE_POSITION_RECONCILE_ENABLED`) is required for correct open legs.
- **In-memory:** `PositionManager` and `OrderManager` are hot paths; `data/agent_open_orders.json` snapshots open orders for crash recovery.

## Paper / non-testnet

- **Authoritative ledger:** PostgreSQL (`trades`, `positions`) via `agent_event_subscriber`.
- **On startup:** `POSITION_RESTORE_ON_STARTUP` loads OPEN rows into `PositionManager`.
- **Reconcile:** Still recommended when connected to a real exchange account.
- **Paper log retention:** `paper_trades.log` and `live_audit.md` rotate per logging config; keep `RESET_PAPER_STATE_ON_STARTUP=false` for long optimization campaigns.

## Kill switch

- **Env:** `TRADING_KILL_SWITCH=true` blocks all new entries (fail closed).
- **Runtime:** Admin `POST /api/v1/admin/agent/emergency-stop` flattens positions, sets context `emergency_stop`, publishes `EmergencyStopEvent`, transitions to `EMERGENCY_STOP`.

## Reconcile gate

When `BLOCK_ENTRIES_ON_RECONCILE_DIVERGENCE=true`, new entries are rejected until local and exchange position sets match after `reconcile_positions_with_exchange()`.

---

## Trade decision snapshot schema v1

Authoritative builder: [`agent/persistence/trade_snapshot.py`](../agent/persistence/trade_snapshot.py).

### Top-level envelope

| Field | Description |
|-------|-------------|
| `snapshot_version` | Integer schema version (default `1`) |
| `snapshot_kind` | `entry`, `closed_round_trip`, or `reject` |
| `captured_at` | ISO-8601 UTC |

### `system_context`

Answers *which strategy revision produced this trade?*

- `decision_engine_mode`, `gate_profile`, `trading_mode`, `trading_symbol`
- Risk knobs: `stop_loss_percentage`, `take_profit_percentage`, `use_atr_scaled_sl_tp`, `max_drawdown`, `agent_daily_drawdown_halt_pct`
- Structural gate envs: `structural_gate_min_trend_age`, `structural_gate_max_failed_breakouts`
- `config_hash` — SHA-256 prefix (8 chars) of sorted canonical JSON of the above (no secrets)
- `session_id` — agent session from `get_session_id()`
- Optional `build_id` from `BUILD_ID` / `GIT_COMMIT` env at deploy

### `decision_context`

Rule-based pipeline subset at entry (or reject):

- `reasoning_chain_id`, `symbol`, `signal`, `side`, `confidence`, `structural_confidence`
- `rule_based_pipeline`: `market_state`, `structural_gates`, `fsm_decision`, `narrative_tail` (last 5)
- `gate_evaluation` — denormalized copy: `categories`, `block_reasons`, `setup_type`, `structural_confidence` (not invented per-gate deltas)
- `features` — curated v43 allowlist only (`TRADE_SNAPSHOT_FEATURE_KEYS` or defaults)
- Risk: `stop_loss`, `take_profit`, `atr_14`, `leverage`, `entry_lots`
- Lifecycle baselines (TLE): `conviction_at_entry`, `evidence_at_entry`, `take_profit_at_entry`, `stop_loss_at_entry`
- Optional `confluence_components` when legacy `trade_score` / `environment_scores` exist

In-memory position fields updated post-fill by TLE: `last_lifecycle_verdict`, `last_health_score`, `last_opportunity_score`, `last_tp_modify_at`. See [trade-lifecycle-engine.md](trade-lifecycle-engine.md).

### `performance_context`

In-memory counters at entry (`agent/persistence/performance_context.py`): `closed_trades_count`, streaks, `rolling_win_rate_50`, session/daily realized PnL, `current_drawdown_pct`. Omitted when disabled or unavailable (no blocking DB read).

### `execution_timing`

Per-trade latency chain (ISO timestamps + deltas on close):

| Stage | Source |
|-------|--------|
| `decision_created_at` | `DecisionReadyEvent` |
| `risk_approved_at` | `RiskApprovedEvent` |
| `order_submitted_at` | start of `execute_trade` |
| `exchange_filled_at` | fill timestamp |
| `position_opened_at` | position `entry_time` |

Close merge adds `decision_to_risk_ms`, `risk_to_fill_ms`, etc.

### Close outcome (`snapshot_kind=closed_round_trip`)

`outcome` block: `exit_price`, `pnl`, `exit_reason`, fees, merged timing.

### Size cap

`TRADE_SNAPSHOT_MAX_BYTES` (default 32768). Truncates `narrative_tail`, `features`, `confluence_components` first; sets `_truncated` when applied.

---

## PostgreSQL tables

### `trade_outcomes`

Closed positions with full merged snapshot in `metadata` JSONB (no migration needed for new snapshot fields).

### `entry_decisions`

Migration `002_entry_decisions`. Rows for `rejected`, `approved`, `executed` with `reject_reason`, `config_hash`, `reasoning_chain_id`, partial or full snapshot in `metadata`.

### `analytics_rollups`

Migration `003_analytics_rollups`. Precomputed buckets: `daily`, `weekly`, `regime`, `setup_type`, `config_hash`. Incremented async on `PositionClosedEvent`.

---

## Agent closed-trade ledger

[`backend/services/agent_trade_ledger_service.py`](../backend/services/agent_trade_ledger_service.py):

- `AGENT_CLOSED_TRADES_MAX_ROWS` (default 5000)
- JSONL archive under `data/agent_closed_trades/archive/` with `manifest.json`
- Summary fields: `setup_type`, `regime`, `gate_categories`, `fsm_state`, `config_hash`, `snapshot_version`, `reasoning_chain_id`

Verify archives: `python tools/commands/trade_analytics.py archive-verify`

---

## Configuration flags

See [`.env.example`](../.env.example):

- `TRADE_ENTRY_SNAPSHOT_ENABLED`, `TRADE_SNAPSHOT_VERSION`, `TRADE_SNAPSHOT_FEATURE_KEYS`, `TRADE_SNAPSHOT_MAX_BYTES`, `TRADE_SNAPSHOT_INCLUDE_PERFORMANCE_CONTEXT`
- `ENTRY_DECISIONS_WRITES_ENABLED`, `TRADE_OUTCOMES_WRITES_ENABLED`
- `THRESHOLD_ADAPTER_REGIME_AWARE` — segment threshold learning by dominant regime when sample size allows
- `BUILD_ID` / `GIT_COMMIT` — optional deploy fingerprint in `system_context`
- `logic_version` — component hashes in `system_context` (`rule_set`, `signal_logic`, `market_validation`, `analysis_engine`, …)
- `TRADE_LIFECYCLE_LOG_ONLY` — TLE observation mode (see [trade-lifecycle-engine.md](trade-lifecycle-engine.md))

### Intelligence platform fields (snapshot v1 extensions)

| Field | Location | Purpose |
|-------|----------|---------|
| `market_validation` | `decision_context` | Pre-trade checks + `validation_score` |
| `signal_explanation` | `decision_context` | Reasons, rejected rules, FSM, confidence |
| `regime_benchmark` | `decision_context` / `market_state` | Analytics cohort label |
| `position_monitoring[]` | root metadata on close | Per-cycle TLE assessments |
| `market_structure_timeline[]` | root metadata on close | Structure evolution sequence |
| `post_trade_assessment` | root metadata on close | 4-dimension quality + root cause |

Facade: [`agent/intelligence/trade_analysis_engine.py`](../agent/intelligence/trade_analysis_engine.py) — unified assessment over snapshot.

Experiment registry: [`data/experiments/registry.json`](../data/experiments/registry.json).

---

## Analytics API

Read-only routes under `/api/v1/analytics/` ([`backend/api/routes/analytics.py`](../backend/api/routes/analytics.py)):

| Endpoint | Purpose |
|----------|---------|
| `GET /trade-outcomes` | Paginated outcomes; filter by regime, setup_type, close_reason, config_hash, date |
| `GET /entry-decisions` | Funnel + reject breakdown |
| `GET /performance-by-regime` | Win rate / PnL by regime |
| `GET /performance-by-config` | Compare `config_hash` cohorts |
| `GET /rollups` | Precomputed daily/regime summaries |
| `GET /attribution-summary` | Root cause + 4-dimension quality breakdown |
| `GET /trade-quality` | Entry/execution/exit/market quality distributions |
| `GET /regime-benchmarks` | Performance by `regime_benchmark` label |
| `GET /rule-evaluation` | Per-rule stats, interactions, FP/FN |
| `GET /confidence-calibration` | Structural confidence bucket vs win rate |

CLI: [`tools/commands/trade_analytics.py`](../tools/commands/trade_analytics.py) — `snapshot-integrity`, `reject-breakdown`, `regime-performance`, `config-diff`, `economic-summary`, `market-validation`, `regime-benchmarks`, `signal-explainability`, `rule-evaluation`, `archive-verify`.

Phase gates: [`tools/commands/phase_readiness_gate.py`](../tools/commands/phase_readiness_gate.py).

---

## Trade Intelligence Snapshot v2

Event-driven decision timelines and enriched entry/close fields. See [trade-intelligence-snapshot-v2.md](trade-intelligence-snapshot-v2.md).

- Append-only `trade_decision_events` table (outside 32KB metadata cap)
- Snapshot v2: `entry_quality`, `hypothesis_snapshot`, slippage, `tp_sl_history`
- MFE/MAE at close, reject forward labels, denormalized `trade_outcomes` columns

---

## Join key for logs and DB

Use **`reasoning_chain_id`** to correlate structlog events, `entry_decisions`, and `trade_outcomes.metadata.decision_context.reasoning_chain_id`.

---

## Docker deploy notes

- Rebuild images after agent/backend code changes: `docker compose build --pull` then `docker compose up -d --force-recreate` ([Deployment](../docs/10-deployment.md)).
- Backend applies Alembic on startup when `AUTO_CREATE_DB_SCHEMA=true`; see [Database maintenance – Alembic](../docs/10-deployment.md#alembic-migrations) if the backend fails with schema drift.
- Analytics CLI against the compose Postgres network: set `DATABASE_URL` to the host-mapped URL or run queries via `docker compose exec postgres psql ...`.
