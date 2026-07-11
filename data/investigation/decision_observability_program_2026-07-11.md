# Decision Observability Program — 2026-07-11

**Status:** Active  
**Parent:** [Thesis Intelligence Program](thesis_intelligence_program_2026-07-13.md)  
**Baseline:** `0503847` / `hold_baseline_policy`

---

## Inflection point

The limiting factor is no longer trading logic or infrastructure — it is **measurement fidelity** for thesis-rule diagnostics.

Two independent problems:

| ID | Problem | Question | Proceed when |
|----|---------|----------|--------------|
| P1 | Measurement fidelity | Can we accurately determine why a rule didn't fire? | Evidence assembler + provenance |
| P2 | Thesis quality | Given accurate features, do thresholds exclude profitable EV? | P1 solved + `N_high_confidence >= 100` |

**Rule:** Problem 2 must not proceed on telemetry-default or missing-feature rows.

---

## Provenance taxonomy

| Source | Confidence | Use in threshold stats |
|--------|------------|------------------------|
| `log_market_context` | high | Yes |
| `telemetry_embedded` | medium | Yes |
| `default_missing` | excluded | **No** |

Per-feature schema:

```json
{
  "feature": "adx_14",
  "value": 22.89,
  "source": "log_market_context",
  "confidence": "high",
  "observed": true
}
```

---

## Sample-size gate

Replay threshold sweeps require:

```
N_high_confidence >= 100
```

where high-confidence = all core thesis features observed from log or telemetry (not excluded).

Reported in every `coverage.json` as `sweep_gate: PASS|FAIL`.

---

## Core thesis features

`adx_14`, `di_spread`, `vol_regime`, `hurst_60`, `h_trend`, `h1_trend`, `rsi_14`, `bb_pos`

---

## G6 framing (closed)

| Criterion | Result |
|-----------|--------|
| Runtime / instrumentation | Met |
| Shadow disagreements | 0 |
| Shadow-only EV | Not estimable |
| Promotion evidence | None |

Vacuous pass — closes ops requirement without policy promotion.

---

## DQI baseline

Week 0 composite: **50.52** ([`dqi_2026-07-11.json`](dqi_2026-07-11.json))

- Track **trend**, not absolute level
- `measurement_coverage` reported as appendix (not blended until stable)

---

## Engineering artifacts

| Artifact | Path |
|----------|------|
| Evidence assembler | [`scripts/signal_recovery/decision_evidence.py`](../../scripts/signal_recovery/decision_evidence.py) |
| Assemble CLI | [`tools/commands/assemble_decision_evidence.py`](../../tools/commands/assemble_decision_evidence.py) |
| Thesis miss (Phase A/B) | [`tools/commands/thesis_rule_miss_analysis.py`](../../tools/commands/thesis_rule_miss_analysis.py) |
| Feature distribution | [`tools/commands/thesis_feature_distribution.py`](../../tools/commands/thesis_feature_distribution.py) |
| Threshold sweep | [`tools/commands/thesis_threshold_sweep.py`](../../tools/commands/thesis_threshold_sweep.py) |

---

## Workflow

```
Operational baseline
        ↓
Evidence enrichment (log + telemetry join)
        ↓
Provenance + coverage report
        ↓
Threshold miss ranking (high-confidence only)
        ↓
Hurst distribution (feature science)
        ↓
Replay threshold sweeps (gated)
        ↓
Governance review
```

---

## Ongoing ops

| Cadence | Command |
|---------|---------|
| Daily | `scripts/daily_validation.ps1` |
| Weekly | `scripts/daily_validation.ps1 -Weekly` |
| WebSocket | 24h operational / 7d production — [`ws_acceptance_2026-07-11.md`](ws_acceptance_2026-07-11.md) |

---

## Future hardening (Phase 6)

Emit core features + provenance at telemetry write time in `agent/core/signal_recovery_telemetry.py` — reduces offline join dependency.
