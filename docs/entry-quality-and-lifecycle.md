# Entry Quality and Lifecycle (Quality-First Pipeline)

Operational reference for the **quality-first** decision architecture: advisory entry scoring, single policy authority, economics validation, and EV-based post-entry management.

**Related**: [Architecture](01-architecture.md), [Logic & Reasoning](05-logic-reasoning.md), [Trade Lifecycle Engine](../reference/trade-lifecycle-engine.md), [v43 trade execution runbook](v43_trade_execution_runbook.md).

---

## Design principles

| Layer | Question | Authority |
|-------|----------|-----------|
| **Entry quality** (`entry_quality.py`) | How good is this trade? | **Advisory** — scores and dimensions only |
| **Reasoning adjudication** (Step 6) | Does thesis align with ML and score? | **Advisory** — narrative + `adjudication_verdict` |
| **Policy engine** (`agent_policy_engine.py`) | Should we trade? | **Authoritative** — emits `PolicyVerdict` / `DECISION_READY.signal` |
| **Exit engine** (`exit_engine.py`) | Should we exit or manage? | **Authoritative** for lifecycle actions when TLE enabled |

Policy consumes quality scores as thresholds; it does not delegate veto authority to `EntryQualityResult`.

---

## Pre-entry pipeline (v43 / IC path)

```text
Market frames → ML validation → Thesis / hypothesis portfolio
  → Entry quality (8 dimensions) → trade_score facade
  → Reasoning (IC minimal + Step 6 adjudication)
  → Policy fusion → adjudication authority hook → quality policy hook
  → Conviction sizing → Risk → Execution
```

### Entry quality dimensions

`evaluate_entry_quality()` in [`agent/core/entry_quality.py`](../agent/core/entry_quality.py) produces:

| Dimension | Inputs |
|-----------|--------|
| `structural` | Thesis direction, confidence, ML alignment |
| `ml` | Gated `final_long`/`final_short`, scaled by collapse trust |
| `economic` | Gate 5 edge vs `round_trip_cost_pct()` (always computed) |
| `regime` | Regime + structure; neutral + low structural → `required_ml_confirmation` |
| `position_context` | Open position, recent exit churn |
| `microstructure` | `spread_bps`, MSO liquidity, vol spikes |
| `trend_stability` | `hurst_60`, `trend_strength_delta` |
| `signal_freshness` | Bars since thesis fire (`thesis_fired_at_bar`) |

Output: `quality_score` (0–100), `passed`, `dimensions`, `required_ml_confirmation`. Stored on `market_context.entry_quality` and in decision telemetry.

### Trade score facade

[`trade_scorer.py`](../agent/core/trade_scorer.py) delegates to `evaluate_entry_quality()`. Legacy callers (`reasoning_engine`, `evidence_engine`, orchestrator) keep the `TradeScoreResult` API; components map to dimension scores × 100.

### Policy authority fixes

1. **`hypothesis_no_rule_fired`** — shared with `thesis_no_rule_fired` via [`hypothesis_reason_codes.py`](../agent/core/hypothesis_reason_codes.py); blocks gated ML when hypothesis aggregate is flat.
2. **Adjudication enforcement** — `apply_adjudication_authority()` forces HOLD when Step 6 verdict is `ml_reject`, `conflict`, or `score_reject` but policy emitted an entry.
3. **Neutral thesis without ML** — `ml_or_thesis` blocks thesis entry in neutral regime when ML gates failed and structural confidence is below floor.
4. **Quality floor** — `apply_entry_quality_policy()` HOLD when `quality_score < ENTRY_QUALITY_MIN_SCORE` or `required_ml_confirmation` without ML confirms.

Step 6 exposes structured `step_metadata.adjudication_verdict` on the reasoning chain.

### Gate 5 economics

Gate 5 (`apply_gate5_min_edge`) is **always evaluated** and recorded in `market_context.gate5_economic`. In permissive/balanced profiles, soft ML gates may still set `final_long`/`final_short`, but the **economic dimension** reflects whether edge clears fees. `ml_edge_score()` in evidence_engine subtracts round-trip cost.

### Collapse rate as ML trust

High `v43_collapse_rate` reduces ML weight in entry quality and conviction (`compute_conviction(..., collapse_rate=)`). It does **not** halt trading.

### Breakout extension

Thesis breakout rules use `bb_pos` extension checks ([`agent_thesis_engine.py`](../agent/core/agent_thesis_engine.py)); no hard ADX ceiling. Config: `AGENT_THESIS_BREAKOUT_BB_POS_MAX`, `AGENT_THESIS_BREAKOUT_BB_POS_SHORT_MIN`.

### ADX chop filter (v43 path)

When `V15_ADX_REGIME_FILTER_ENABLED=true` (code default **on** since Jul 2026), [`trading_handler.py`](../agent/events/handlers/trading_handler.py) applies ADX filters on the v43 entry path (previously skipped when structural quality was high):

| Reject reason | Condition |
|---------------|-----------|
| `adx_ranging_filter` | `adx_14` below `ADX_RANGING_THRESHOLD` (weak trend / chop) |
| `v15_adx_trending_filter` | `adx_14` above `V15_ADX_RANGING_MAX` (strong trend; v15 ranging-only profile) |

Set `V15_ADX_REGIME_FILTER_ENABLED=false` to restore the legacy v43 bypass when structural quality ≥ 0.5.

---

## Post-entry pipeline (TLE)

When `TRADE_LIFECYCLE_ENABLED=true`:

```text
Open position → PositionIntelligence.evaluate()
  → position_forecast_adapter (cognition expectation vs entry snapshot)
  → ExitEngine.decide() → LifecycleVerdict → trading_handler
```

| Module | Role |
|--------|------|
| [`position_intelligence.py`](../agent/core/position_intelligence.py) | Health, opportunity, continuation alignment |
| [`position_forecast_adapter.py`](../agent/core/position_forecast_adapter.py) | Maps live `decision_context_v3.expectation` to lifecycle hints (`exit_candidate`, `extend_tp`, `reduce_tp`, `tighten`) |
| [`exit_engine.py`](../agent/core/exit_engine.py) | EV arbiter: stay vs exit, fee-aware hold |
| [`trade_lifecycle_engine.py`](../agent/core/trade_lifecycle_engine.py) | Backward-compat wrapper; tighten/extend TP logic |

### Position forecast adapter

[`evaluate_forecast_adjustment()`](../agent/core/position_forecast_adapter.py) compares live cognition expectation to the entry snapshot:

- **Entry expectation path**: `decision_context["decision_context_v3"]["expectation"]` (as persisted by [`trade_snapshot.py`](../agent/persistence/trade_snapshot.py)); flat `decision_context["expectation"]` is a legacy fallback.
- **Directionless labels**: `expectation_engine` emits `trend_continuation`, `breakout`, `reversal`, `vol_expansion` — not `bullish`/`bearish`. Alignment combines the dominant label with `understanding.direction_bias` (`LONG`/`SHORT`):
  - `trend_continuation` / `breakout` → favors current `direction_bias`
  - `reversal` → favors the opposite of `direction_bias`
  - `vol_expansion` / `neutral` / missing bias → **unknown** (`None`); must not force `exit_candidate`
- **Legacy vocabulary**: explicit directional labels (`bullish`, `bearish`, etc.) still work for backward compatibility.

Misaligned forecasts with confidence ≥ 0.55 feed health-score penalties in TLE; aligned confidence upgrades can trigger `extend_tp` hints.

**EV exit** (`TRADE_LIFECYCLE_EV_EXIT_ENABLED=true`, default): avoids health-only exits when opportunity is high and continuation is valid (fee-aware hold when unrealized PnL &lt; round-trip cost). Opposite signal and `fsm_thesis_broken` remain hard exits.

**Promotion**: Run multi-regime replay before first live enable — see [Trade Lifecycle Engine](../reference/trade-lifecycle-engine.md#promotion-gate-phase-2b--3). After the forecast-adapter fix (Jul 2026), `exit_agreement_rate` should move off 0.0 when `TRADE_LIFECYCLE_LOG_ONLY=false`.

---

## Post-trade learning (optional)

When `ENTRY_QUALITY_LEARNING_ENABLED=true` (default **off**; use `ENTRY_QUALITY_LEARNING_SHADOW_MODE=true` first):

On `POSITION_CLOSED`, `post_trade_analyzer` → `apply_dimension_calibration_feedback()` adjusts dimension weight offsets (bounded by `REFLECTION_CALIBRATION_STEP_SIZE`). Separate from policy fusion rules.

---

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENTRY_QUALITY_MIN_SCORE` | `55` | Policy HOLD floor on advisory quality score |
| `ENTRY_QUALITY_STRUCTURAL_CONF_FLOOR_NEUTRAL` | `0.65` | Neutral regime: require ML when structural below this |
| `ENTRY_QUALITY_COLLAPSE_TRUST_CAP` | `0.95` | Max collapse rate for ML trust scaling |
| `ENTRY_QUALITY_FRESHNESS_HALF_LIFE_BARS` | `6` | Signal freshness decay |
| `ENTRY_QUALITY_MICROSTRUCTURE_SPREAD_BPS_MAX` | `30` | Spread penalty threshold |
| `ENTRY_QUALITY_LEARNING_ENABLED` | `false` | Post-trade dimension calibration |
| `ENTRY_QUALITY_LEARNING_SHADOW_MODE` | `true` | Log calibration without applying |
| `TRADE_LIFECYCLE_EV_EXIT_ENABLED` | `true` | EV arbiter vs legacy health-only exit |
| `TRADE_LIFECYCLE_FEE_AWARE_HOLD_ENABLED` | `true` | Hold when exit locks in fee-dominated loss |
| `TRADE_LIFECYCLE_ENABLED` | `false` in code; `true` in `.env.example` | Master TLE switch |
| `TRADE_LIFECYCLE_LOG_ONLY` | `false` | When `true`, evaluate/log without executing lifecycle actions |
| `POSITION_FORECAST_ADAPTER_ENABLED` | `true` | Cognition expectation hints into TLE health scoring |
| `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` | `0.75` | Gate 5: min edge vs round-trip cost (was `0.2` throughput-recovery default) |
| `V15_ADX_REGIME_FILTER_ENABLED` | `true` | ADX chop/trend filters on v43 entries |
| `ADX_RANGING_THRESHOLD` | `15` | Reject when `adx_14` below this (chop) |
| `V15_ADX_RANGING_MAX` | `25` | Reject when `adx_14` above this (strong trend) |
| `EXIT_ENGINE_MIN_STAY_EV_DELTA` | `0` | Minimum EV delta to prefer exit |
| `UNIFIED_PIPELINE_ENABLED` | `false` | Deferred PR6: `single_decision_engine` consolidation |
| `AGENT_THESIS_BREAKOUT_BB_POS_MAX` | `0.85` | Long breakout extension veto |
| `AGENT_THESIS_BREAKOUT_BB_POS_SHORT_MIN` | `0.15` | Short breakout extension veto |

`AGENT_TRADE_SCORE_MIN` remains the legacy alias referenced by adjudication gated-ML floor; entry quality uses `ENTRY_QUALITY_MIN_SCORE` for policy.

---

## Testing and replay

| Asset | Purpose |
|-------|---------|
| `tests/unit/test_entry_quality.py` | Dimension scoring, collapse trust |
| `tests/unit/test_exit_engine.py` | EV arbiter, fee-aware hold |
| `tests/unit/test_position_forecast_adapter.py` | Expectation vocabulary + nested entry snapshot alignment |
| `tests/fixtures/july2_telemetry/` | Frozen bad-entry cycles |
| `tests/integration/test_july2_telemetry_replay.py` | Policy blocks flat-hypothesis ML |
| `tools/commands/monte_carlo_replay.py` | Randomized slippage/fee expectancy |
| `tools/commands/run_tle_investigation.py` | June/July lifecycle replay |

Success criteria: **fewer bad trades**, not zero trades on a single day.

---

## Deferred consolidation

[`single_decision_engine.py`](../agent/core/single_decision_engine.py) wraps adjudication + quality policy when `UNIFIED_PIPELINE_ENABLED=true`. Keep **off** until PR1–5 validated across regimes in paper trading (≥2 weeks).
