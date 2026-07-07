# Cognitive Architecture

Reference specification for JackSparrow's modular intelligence layer (DecisionContext v3).

## Overview

Each closed bar produces an immutable **DecisionContext** assembled by `DecisionContextBuilder`.
Modules write exactly one slice; no shared mutable `market_context` dict inside cognition.

## Acyclic dependency graph

```text
Features → Understanding → Expectation (indicators)
                        → Memory (narrative + decay)
                        → Scenario (needs Memory)
                        → Risk Intelligence
                        → Strategy Selector (eligibility)
                        → Strategy Scorer (confidence)
                        → Hypothesis Engine
                        → Policy → Execution
```

**Forbidden reads:**

- Expectation: no portfolio, hypothesis, risk output
- Scenario: no portfolio, hypothesis, selector
- Risk: no hypothesis, policy
- Selector: no hypothesis

## Slices

| Slice | Module | Question |
|-------|--------|----------|
| `understanding` | MarketUnderstandingEngine | What is true now? |
| `memory` | MemoryEngine | How did we get here? |
| `expectation` | ExpectationEngine | What do we expect next? |
| `scenario` | ScenarioEngine | What phase is building? |
| `risk_intelligence` | RiskIntelligence | Is risk acceptable? |
| `strategy_selection` | StrategySelector | Who is eligible? |
| `strategy_scores` | StrategyScorer | How confident per profile? |

Narrative remains append-only under `data/market_narrative/`; it is not a DecisionContext slice.

## Immutability rules

1. Slices are frozen dataclasses.
2. Only `DecisionContextBuilder.with_<slice>()` mutates during assembly.
3. Modules receive `CognitionInputs` (typed read view).
4. `ReasoningArtifact` records inputs, outputs, reason_codes, duration_ms per module.

## Shadow rollout

| Flag | Default | Testnet (2026-07-06) | Effect |
|------|---------|----------------------|--------|
| `COGNITION_SHADOW_ENABLED` | true | **true** | Run full cognition cycle; log only |
| `COGNITION_EXPECTATION_ENABLED` | false | false | Authoritative expectation |
| `COGNITION_MEMORY_ENABLED` | false | false | Authoritative memory |
| `COGNITION_SCENARIO_ENABLED` | false | false | Authoritative scenario |
| `COGNITION_RISK_ENABLED` | false | false | Authoritative risk slice |
| `COGNITION_SELECTOR_ENABLED` | false | **true** (Stage 1) | Filter thesis families |
| `COGNITION_SCORER_ENABLED` | false | **true** (Stage 2) | Scorer weights in hypothesis aggregate |
| `COGNITION_TEMPORAL_AUTHORITY_ENABLED` | false | false (Stage 4B pending) | Post-cognition trade_score / ml_confirms / entry_quality |

Logical authority (selector + scorer) is **live on India testnet Docker**. Temporal authority remains off until Stage 5 shadow completes. See [Rule-Based Decision Engine – Cognition rollout](../docs/rule-based-decision-engine.md#cognition-authority-rollout-v2).

## Provisional vs authoritative thesis

Two thesis paths coexist during rollout:

| Path | Source | Used for |
|------|--------|----------|
| **Provisional** | `thesis_verdict_cached` (~orchestrator L900) | Market-intel gating, `should_run_full_prediction`, IC divergence diagnostics, `cognition_thesis_authority_compare` replay |
| **Authoritative** | `evaluate_thesis_from_context` after `attach_cognition` | Hypothesis snapshot, policy inputs, and (after Stage 4B) `trade_score`, `ml_confirms`, `entry_quality` |

After **Stage 4B** (`COGNITION_TEMPORAL_AUTHORITY_ENABLED=true`), execution-facing consumers must use the authoritative path. Provisional thesis remains for diagnostics only — it must not drive execution.

Pipeline order (v43):

```text
provisional thesis → ML raw gates (final_long/short)
        ↓
populate_rule_based → attach_cognition → evaluate_thesis_from_context
        ↓
run_post_cognition_adjudication (shadow or effective per flags)
        ↓
build_evidence_stack → policy_verdict
        ↓
cognition_thesis_authority_compare (telemetry)
```

## Stage 5 validation ladder

Before enabling **Stage 4B** (`COGNITION_TEMPORAL_AUTHORITY_ENABLED=true`) or live execution authority:

1. **Replay** — `tools/cognition_rollout_report.py` green vs `phase0_baseline.json` at each stage
2. **Shadow (48–72h)** — Docker logs: zero attach failures; archive `cognition_thesis_authority_compare`
3. **Paper trading (7d)** — PnL/risk vs control; entry rate within bounds
4. **Live sign-off** — Human gate; enable temporal authority only after completing 1–3

**Current position (2026-07-06):** Stages 1–2 deployed on testnet; Step 2 (shadow observation) in progress. Stage 4B must not be enabled until shadow + paper gates pass.

## Memory decay

Behavioral events decay as `exp(-age_bars / half_life)` (default half_life=10 bars).
Selector uses weighted sums, not raw counts.

## Replay

- **Calibration**: expectation vs outcome at T+N
- **What-if**: evaluate all strategy profiles per bar (`agent/testing/cognition_replay.py`)
- **Rollout regression**: pinned scenarios + stage diffs (`tools/cognition_rollout_report.py`); artifacts under `logs/agent/cognition_rollout/`

## Extension

New strategies register in `strategy_profiles.py` only; no orchestrator changes required.

## Docker

Application code is baked into images. After cognition rollout changes:

```bash
docker compose build agent
docker compose up -d --force-recreate agent
```

Flag-only changes (no code): `docker compose up -d --force-recreate agent` is sufficient — agent loads `.env.example` then root `.env`.

Verify deployment:

```bash
docker compose logs agent 2>&1 | grep cognition_config_effective
# Expect: shadow=true selector=true scorer=true temporal_authority=false

docker compose logs agent 2>&1 | grep cognition_thesis_authority_compare | tail -3
```

See [Deployment – Cognition authority rollout](../docs/10-deployment.md#cognition-authority-rollout-testnet) and [Rule-Based Decision Engine](../docs/rule-based-decision-engine.md#cognition-authority-rollout-v2).
