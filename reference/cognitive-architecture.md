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

| Flag | Default | Effect |
|------|---------|--------|
| `COGNITION_SHADOW_ENABLED` | true | Run full cognition cycle; log only |
| `COGNITION_EXPECTATION_ENABLED` | false | Authoritative expectation |
| `COGNITION_MEMORY_ENABLED` | false | Authoritative memory |
| `COGNITION_SCENARIO_ENABLED` | false | Authoritative scenario |
| `COGNITION_RISK_ENABLED` | false | Authoritative risk slice |
| `COGNITION_SELECTOR_ENABLED` | false | Filter thesis families |
| `COGNITION_SCORER_ENABLED` | false | Scorer weights in hypothesis aggregate |

Live trade signals unchanged until authoritative flags enabled and validated via replay.

## Memory decay

Behavioral events decay as `exp(-age_bars / half_life)` (default half_life=10 bars).
Selector uses weighted sums, not raw counts.

## Replay

- **Calibration**: expectation vs outcome at T+N
- **What-if**: evaluate all strategy profiles per bar (`agent/testing/cognition_replay.py`)

## Extension

New strategies register in `strategy_profiles.py` only; no orchestrator changes required.

## Docker

Application code is baked into images. After pulling cognition changes:

```bash
docker compose build agent backend frontend
docker compose up -d --force-recreate
```

Validate shadow attach: `docker compose logs agent 2>&1 | grep decision_context_v3_attached`

See [Deployment – Docker Compose](../docs/10-deployment.md#docker-compose-deployment).
