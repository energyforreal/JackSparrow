# Trade Intelligence Snapshot v2

Extends [trading-persistence-model.md](trading-persistence-model.md) with event-driven decision timelines and enriched entry/close snapshots.

## Three layers

| Layer | Role |
|-------|------|
| Runtime | Full per-cycle intelligence (TLE, continuation, hypothesis, policy) |
| Persistence | `trade_outcomes.metadata` + append-only `trade_decision_events` |
| Learning | Consumes persisted dimensions, labels, and causal chains |

## Snapshot v2 envelope

Same top-level shape as v1 with `snapshot_version: 2`. New `decision_context` fields:

| Field | Description |
|-------|-------------|
| `entry_quality` | Full `EntryQualityResult` dict |
| `hypothesis_snapshot` | Competing hypotheses, long/short pressure |
| `policy_verdict` | Signal, conviction, reason_codes, abstention |
| `thesis_verdict` | Thesis engine summary at entry |

`execution_timing` additions: `execution_slippage_bps_entry`, `reference_price_entry`, `fill_price_entry`.

`outcome` additions: `reference_price_exit`, `fill_price_exit`, `execution_slippage_bps_exit`, `tp_sl_history`, `excursions` (MFE/MAE).

## DecisionEvent schema

Authoritative builder: [`agent/persistence/decision_events.py`](../agent/persistence/decision_events.py).

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUID |
| `position_id` | string | Open leg id |
| `reasoning_chain_id` | string | Join key to logs and entry_decisions |
| `symbol` | string | Trading symbol |
| `event_type` | string | See event types below |
| `bar_index` | int? | Candle index when known |
| `sequence_num` | int | Monotonic per position |
| `captured_at` | ISO-8601 | UTC timestamp |
| `caused_by` | string[] | Parent event_ids |
| `delta` | object? | `{field, from, to, magnitude}` |
| `payload` | object | Type-specific body |

### Event types

| Type | When emitted |
|------|----------------|
| `entry_decision` | Post-fill with v2 entry snapshot |
| `regime_shift` | Regime label changes during open position |
| `structure_transition` | Structure state changes |
| `feature_threshold` | Feature crosses configured threshold |
| `conviction_change` | Conviction delta exceeds min threshold |
| `gate_lost` | Structural gate category flips false |
| `continuation_invalidation` | New invalidation code from continuation_thesis |
| `tle_verdict` | TLE cycle with action/health/opportunity |
| `tp_sl_modified` | SL or TP ratchet applied |
| `lifecycle_exit` | Lifecycle-driven exit trigger |
| `close_outcome` | Position closed |
| `mfe_mae_computed` | Excursions computed at close |

### Causality rules

- `continuation_invalidation` may `caused_by` prior `regime_shift` or `feature_threshold` in same cycle.
- `tle_verdict` with action `EXIT` links to recent `continuation_invalidation` events.
- `lifecycle_exit` links to triggering `tle_verdict`.
- `close_outcome` links to `lifecycle_exit` or final `tle_verdict`.

Materialized `causality_graph` on close metadata is a derived summary; primary store is `trade_decision_events`.

## Storage

| Store | Contents |
|-------|----------|
| `trade_decision_events` | Append-only event stream (PostgreSQL) |
| `data/decision_events/{position_id}.jsonl` | Fallback when DB unavailable |
| `trade_outcomes.metadata` | Lean snapshot + `decision_event_count` pointer |
| `entry_decision_labels` | Forward outcomes for rejected entries |

## Configuration

See `.env.example`:

- `TRADE_DECISION_EVENTS_ENABLED` — emit decision events (default false)
- `TRADE_DECISION_EVENTS_SHADOW_MODE` — dual-write without analytics cutover (default true)
- `TRADE_SNAPSHOT_VERSION` — 1 or 2
- `TRADE_DECISION_EVENT_MIN_CONVICTION_DELTA` — conviction change threshold
- `TRADE_MFE_MAE_AT_CLOSE_ENABLED` — async excursions at close
- `TRADE_INTELLIGENCE_LEARNING_ENABLED` — consume v2 artifacts in learning loop
- `TRADE_INTELLIGENCE_LEARNING_SHADOW_MODE` — log nudges only

## Phase gates

CLI: `python tools/commands/phase_readiness_gate.py --gate v2_events`

| Gate | Threshold |
|------|-----------|
| `v1_to_v2_snapshot` | entry_quality coverage >= 95% |
| `v2_events` | decision events on >= 90% closes |
| `v2_causality` | lifecycle_exit trades have >= 2 causal links |
| `v2_mfe_mae` | excursions on >= 90% closes |
| `v2_reject_labels` | >= 50 labeled rejects |
