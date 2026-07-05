# Rule-Based Decision Engine

Operational guide for the **ML-free decision pipeline**: Market Understanding → Market Narrative → Structural Gates → Market FSM → Risk → Execution.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

See also: [Architecture](01-architecture.md), [Logic & Reasoning](05-logic-reasoning.md), [Deployment](10-deployment.md).

---

## Overview

The rule-based engine evaluates **deterministic market facts** and an **evolving narrative** each closed bar. Trade permission and lifecycle state come from categorical structural gates and a finite state machine—not from ML threshold crossing.

The **data layer is unchanged**: `candle_store` → rolling OHLCV buffers → v43 feature matrix (`iloc[-2]` closed bar).

| Mode | `DECISION_ENGINE_MODE` | Behavior |
|------|------------------------|----------|
| Legacy (default) | `ml_legacy` | IC predict + `AgentPolicyEngine` fusion; rule-based pipeline runs in **shadow** when shadow flags are on |
| Rule-based cutover | `rule_based` | Skips ML inference; `_process_rule_based_prediction` owns `DECISION_READY` |
| FSM enforce (bridge) | `ml_legacy` + `MARKET_FSM_ENFORCE=true` | ML path runs but FSM `entry_signal` overrides policy when gates pass |

---

## Pipeline

```text
Feature matrix (closed bar)
        ↓
Market Understanding Engine   → MarketStateSnapshot
        ↓
Market Narrative Engine       → data/market_narrative/{symbol}.jsonl
        ↓
Structural Gate Engine        → 6 categories (all must pass)
        ↓
Market FSM                    → data/market_fsm/{symbol}.json
        ↓
Risk manager + execution
```

### Components

| Module | Path | Responsibility |
|--------|------|----------------|
| Types | `agent/intelligence/market_types.py` | `MarketStateSnapshot`, `StructuralGateResult`, `FSMDecision` |
| Understanding | `agent/intelligence/market_understanding_engine.py` | Trend, breakout, liquidity, MTF roles, trend age from feature history |
| Narrative | `agent/intelligence/market_narrative_engine.py` | Append-only events (`breakout_confirmed`, `pullback_ends`, …) |
| Structural gates | `agent/core/structural_gate_engine.py` | Trend / Structure / Breakout / Liquidity / Volatility / Risk |
| FSM | `agent/intelligence/market_fsm.py` | `Watching` → … → `EntryReady` → `PositionActive` → … |
| Orchestrator | `agent/intelligence/rule_based_pipeline.py` | Single `run_cycle()` + shadow logging |
| Archetypes | `agent/intelligence/trade_archetype_memory.py` | Structured trade memory on `POSITION_CLOSED` |

### Structural gate categories

All six must pass for `trade_allowed`:

- **Trend** — direction, strength, minimum trend age (`STRUCTURAL_GATE_MIN_TREND_AGE`)
- **Structure** — `market_structure` (no crisis/chop)
- **Breakout** — confirmed setup + optional retest (`STRUCTURAL_GATE_BREAKOUT_REQUIRE_RETEST`)
- **Liquidity** — spread / structure liquidity flags
- **Volatility** — expansion required for breakout entries
- **Risk** — open position, debounce, freq cap (re-homed from `v43_signal_gates`)

### FSM states

```text
Watching → TrendDeveloping → SetupForming → EntryReady
    → PositionActive → Managing → ExitReady → Watching
```

`EntryReady` + `trade_allowed` → `entry_signal` LONG/SHORT. Risk approval transitions to `PositionActive` via `market_fsm.on_position_opened()`.

---

## Configuration

Root [`.env.example`](../.env.example):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DECISION_ENGINE_MODE` | `ml_legacy` | `ml_legacy` \| `rule_based` |
| `MARKET_UNDERSTANDING_SHADOW_ENABLED` | `true` | Run understanding each cycle |
| `MARKET_NARRATIVE_SHADOW_ENABLED` | `true` | Run narrative each cycle |
| `STRUCTURAL_GATE_SHADOW_ENABLED` | `true` | Run structural gates each cycle |
| `STRUCTURAL_GATE_SHADOW_LOG_ONLY` | `true` | Log shadow without blocking ML entries |
| `MARKET_FSM_SHADOW_ENABLED` | `true` | Run FSM each cycle |
| `MARKET_FSM_ENFORCE` | `false` | FSM overrides policy signal |
| `STRUCTURAL_GATE_MIN_TREND_AGE` | `3` | Minimum trend age (bars) |
| `STRUCTURAL_GATE_MAX_FAILED_BREAKOUTS` | `2` | Narrative veto threshold |
| `STRUCTURAL_GATE_BREAKOUT_REQUIRE_RETEST` | `true` | Require retest for breakout setups |
| `ARCHETYPE_MEMORY_SHADOW` | `true` | Log similarity hints only |

### Cognitive layer (DecisionContext v3)

Shadow mode is **on by default** (`COGNITION_SHADOW_ENABLED=true`). The orchestrator attaches `decision_context_v3` to `market_context` each cycle without changing live signals until authoritative flags are enabled.

| Variable | Default | Purpose |
|----------|---------|---------|
| `COGNITION_SHADOW_ENABLED` | `true` | Run full cognition cycle; log slices + `ReasoningArtifact`s |
| `COGNITION_EXPECTATION_ENABLED` | `false` | Authoritative expectation engine |
| `COGNITION_MEMORY_ENABLED` | `false` | Authoritative market memory |
| `COGNITION_SCENARIO_ENABLED` | `false` | Authoritative scenario phase |
| `COGNITION_RISK_ENABLED` | `false` | Authoritative risk intelligence slice |
| `COGNITION_SELECTOR_ENABLED` | `false` | Filter thesis families by strategy selector |
| `COGNITION_SCORER_ENABLED` | `false` | Apply scorer weights in hypothesis aggregate |
| `COGNITION_MEMORY_DECAY_HALF_LIFE_BARS` | `10` | Behavioral memory decay half-life (5m bars) |

Acyclic order: **Expectation → Memory → Scenario → Risk → Selector → Scorer → Hypothesis**. Full spec: [Cognitive Architecture](../reference/cognitive-architecture.md).

### Rollout order (recommended)

1. Deploy with defaults (`ml_legacy`, shadow on) — compare logs
2. Validate cognition shadow: `pytest tests/unit/cognition/` or `python run_scenario_tests.py --cognition`
3. `MARKET_FSM_ENFORCE=true` on testnet
4. `DECISION_ENGINE_MODE=rule_based`
5. Enable `COGNITION_SELECTOR_ENABLED` / `COGNITION_SCORER_ENABLED` after replay sign-off
6. `ARCHETYPE_MEMORY_SHADOW=false` (optional sizing hints)

---

## Cognitive layer (DecisionContext v3)

Parallel to the structural pipeline, the **cognition package** (`agent/intelligence/cognition/`) assembles an immutable **`DecisionContext`** each bar:

```text
Understanding → Expectation → Memory → Scenario → Risk Intelligence
        → Strategy Selector → Strategy Scorer → (Hypothesis / Policy downstream)
```

| Slice | Module | Writes |
|-------|--------|--------|
| `understanding` | Existing market understanding | Present-tense facts |
| `expectation` | `expectation_engine.py` | Forward scenarios per horizon (10m–2h) |
| `memory` | `memory_engine.py` | Decayed behavioral history |
| `scenario` | `scenario_engine.py` | Phase (compression, markup, …) |
| `risk_intelligence` | `risk_intelligence.py` | `trade_environment_score` |
| `strategy_selection` | `strategy_selector.py` | Profile eligibility |
| `strategy_scores` | `strategy_scorer.py` | Confidence + consensus |

Payload on `market_context` / trade snapshots: **`decision_context_v3`** (dict). Signal explainer may include `cognition` block (scenario, expectation horizons, strategy ranking).

### Cognition observability

| Event / field | When |
|---------------|------|
| `decision_context_v3_attached` | Shadow attach succeeded (debug) |
| `decision_context_v3` on entry snapshot | Trade snapshot v2 enrichment |
| `run_scenario_tests.py --cognition --what-if` | Scenario replay + counterfactual profiles |

---

## Observability

### Structlog events

| Event | When |
|-------|------|
| `market_understanding_snapshot` | Each understanding evaluation |
| `market_narrative_event` | New narrative event detected |
| `structural_gate_shadow` | Gate category pass/fail |
| `fsm_shadow_decision` | FSM state + entry_signal |
| `rule_based_pipeline_shadow` | Shadow vs live policy comparison |
| `trade_archetype_similarity` | Post-close archetype lookup |

### Log analyzer

```bash
docker logs jacksparrow-agent 2>&1 | python tools/analyze_agent_logs.py
```

Reports: decision cycles, gated-ML-neutral entries, BUY→HOLD flips, shadow block rate.

---

## API / UI payloads

`DecisionReadyEvent` and WebSocket `signal` include (when rule-based pipeline ran):

| Field | Description |
|-------|-------------|
| `market_state` | Full `MarketStateSnapshot` dict |
| `narrative_tail` | Last N narrative events |
| `structural_gates` | Category pass/fail + `setup_type` |
| `fsm_state` | Current FSM state |
| `entry_signal` | FSM entry intent (actionable when flat + `EntryReady`) |
| `thesis_health` | `healthy` \| `weakening` \| `broken` |
| `position_lifecycle` | `watching` \| `entry_ready` \| `managing` \| `exit_ready` |
| `decision_context_v3` | Cognition slices (shadow when `COGNITION_SHADOW_ENABLED=true`) |

### Frontend

- **Trading tab**: `MarketStateCard`, `NarrativeTimeline` ([`Dashboard.tsx`](../frontend/app/components/Dashboard.tsx))
- **Signal card**: shows `position_lifecycle` when managing (fixes BUY→HOLD confusion)
- **Active positions**: FSM state + thesis health badges

---

## Entry validation

When `DECISION_ENGINE_MODE=rule_based`, [`entry_validation_guard.py`](../agent/core/entry_validation_guard.py) requires:

- FSM `EntryReady`
- Structural `trade_allowed`
- Policy reason `rule_based_fsm_entry`

---

## Docker

Code is baked into images (no bind-mount of `agent/`). After changes:

```bash
docker compose build agent backend frontend
docker compose up -d --force-recreate
```

See [Deployment – Docker Compose](10-deployment.md#docker-compose-deployment).

---

## Tests

```bash
pytest agent/tests/test_rule_based_pipeline.py agent/tests/test_rule_based_scenarios.py
pytest tests/unit/cognition/
python run_scenario_tests.py --cognition
```
