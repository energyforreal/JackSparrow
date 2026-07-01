# Trade Lifecycle Engine (TLE)

Symmetrical post-entry intelligence for open positions. Enabled with `TRADE_LIFECYCLE_ENABLED=true`.

## Purpose

Pre-entry path runs full intelligence → conviction → decision. Without TLE, post-entry collapses to static SL/TP monitoring. TLE reuses the same candle pipeline to answer:

1. Should I still hold? (risk / thesis validity)
2. Should I let profits run or lock sooner? (opportunity / TP adaptation)

## Action space

| Action | Meaning |
|--------|---------|
| `HOLD` | No intelligence-driven change this candle |
| `TIGHTEN_SL` | Ratchet stop loss toward price (never loosen) |
| `MODIFY_TP` | Extend or reduce take-profit (`tp_direction`: `extend` \| `reduce`) |
| `EXIT` | Close position (`exit_reason=lifecycle_exit`) |

Mechanical SL/TP/trailing in `manage_position` remains a hard backstop between candles.

## Dual-axis scoring

- **TradeHealth (0–100)** — deterioration: continuation alignment, conviction drop, flip risk, FSM weakening/broken, opposite signal / ML reversal
- **TradeOpportunity (0–100)** — strengthening: conviction rise, continuation alignment, trending regime, FSM healthy, intel diff tailwinds

## Arbiter priority (first match per candle)

1. Health below exit threshold OR hard invalidation → **EXIT**
2. Health in tighten band OR elevated flip score → **TIGHTEN_SL** (may combine with MODIFY_TP reduce via `apply_lifecycle_modify_levels`)
3. Opportunity above extend threshold, conviction delta ≥ extend minimum, continuation aligned → **MODIFY_TP** extend
4. Health weakening but above exit, opportunity fading → **MODIFY_TP** reduce
5. Otherwise → **HOLD**

## TP ratchet invariants

**Long**

- Extend: `new_tp >= current_tp`
- Reduce: `current_price < new_tp < current_tp`

**Short** — mirror inverted.

Throttle: `TRADE_LIFECYCLE_TP_MODIFY_MIN_INTERVAL_SECONDS`, `TRADE_LIFECYCLE_TP_MODIFY_MIN_CHANGE_PCT`.

## Key modules

| Module | Role |
|--------|------|
| `agent/core/continuation_thesis.py` | Entry snapshot vs live `market_context` alignment |
| `agent/core/trade_lifecycle_engine.py` | Scores, arbiter, `LifecycleVerdict` |
| `agent/events/handlers/trading_handler.py` | `DecisionReady` integration when positioned |
| `agent/core/execution.py` | `apply_lifecycle_tighten`, `apply_lifecycle_modify_tp`, `apply_lifecycle_modify_levels` |

## Authority when enabled

| Priority | Source |
|----------|--------|
| 1 | Emergency / stale data |
| 2 | Exchange bracket flat |
| 3 | TLE EXIT |
| 4 | TLE MODIFY_TP |
| 5 | TLE TIGHTEN_SL |
| 6 | Price SL/TP/trailing (tick) |
| 7 | Legacy signal_reversal / ml_reversal / dynamic bracket — **disabled** |

## Configuration

See `TRADE_LIFECYCLE_*` settings in `agent/core/config.py`.

## Observability

Structured log event: `trade_lifecycle_verdict`. Markdown audit: `append_trade_lifecycle_verdict` in `signal_audit_md.py` (includes `tp_before` / `tp_after`).

## Position fields

Persisted at fill and updated each verdict:

- `conviction_at_entry`, `evidence_at_entry`
- `take_profit_at_entry`, `stop_loss_at_entry`
- `last_lifecycle_verdict`, `last_health_score`, `last_opportunity_score`
- `last_tp_modify_at`

## Observation mode (Phase 2)

Set `TRADE_LIFECYCLE_LOG_ONLY=true` with `TRADE_LIFECYCLE_ENABLED=true` to evaluate and log verdicts **without** executing `EXIT` / `TIGHTEN_SL` / `MODIFY_TP`. Bracket SL/TP remains the live exit path.

Per-cycle records append to `lifecycle_monitoring[]` on the open position and merge into `trade_outcomes.metadata.position_monitoring` on close. Each record includes `health_score`, `opportunity_score`, `action_would_be`, `structure_state`, `structure_transition`, and distance-to-TP/SL estimates.

`market_structure_timeline[]` on close condenses structure evolution (e.g. `bullish → neutral → bearish`).

## Promotion gate (Phase 2b → 3)

Before enabling live TLE (`TRADE_LIFECYCLE_LOG_ONLY=false`), run:

```bash
python tools/commands/tle_agreement_score.py --start YYYY-MM-DD --end YYYY-MM-DD
python tools/commands/phase_readiness_gate.py --gate 2b_to_3
```

Targets: `overall_agreement ≥ 0.80`, `exit_agreement_rate ≥ 0.75`, `opportunity_precision ≥ 0.65`.
