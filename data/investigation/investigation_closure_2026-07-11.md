# Investigation Closure — 2026-07-11

**Status:** Closed  
**Milestone:** Signal Quality & Continuous Validation (replaces Policy Optimization)

---

## Baseline freeze

| Field | Value |
|-------|-------|
| Baseline commit | `0503847` |
| Policy decision | `hold_baseline_policy` |
| 3A.2 (`AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`) | **Not promoted** |
| Promotion rationale | G2 net EV fail, G4 non-ranging EV fail, G6 forward shadow incomplete |

This baseline is the reference point for all future replay, shadow, and calibration comparisons.

---

## Investigation outcome

**Original hypothesis (falsified):** The agent is not trading because policy is too conservative.

**Supported conclusion:** Policy thesis fusion is the active rejection mechanism under observed
market conditions. Tested relaxations (`ml_only`, `no_thesis_veto`, `ml_adopt_flat`) produced
negative realized expectancy under counterfactual replay assumptions (12h and 30d windows).

See [`forensic_report_2026-07-11.md`](forensic_report_2026-07-11.md) for full evidence chain.

---

## Evidence matrix

| Question | Answer | Evidence level |
|----------|--------|----------------|
| Infrastructure healthy? | Yes | Observed |
| Market data healthy? | Yes | Observed |
| `AGENT_START_MODE=MONITORING` suppressing trades? | No | Observed |
| ML generating signals? | Yes | Observed |
| Policy rejecting signals? | Yes | Observed + Derived |
| Alternative policy better under replay assumptions? | No | Experimental |
| Should production policy change now? | Not justified | Engineering judgment |

---

## Governance — policy change requirements

Every future policy change requires **all** of:

1. Rolling replay (7d + 30d) shows positive net EV for the proposed scenario
2. Forward shadow (G6) non-negative realized EV over 48h+ OOS window
3. Regime-stratified validation — not only neutral/ranging
4. Promotion gate review documented in `data/investigation/`
5. Explicit approval against baseline `0503847`

**Do not change without evidence:**

- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`
- `AGENT_TRADE_SCORE_MIN`
- ADX trending filter
- Global thesis gating relaxation

---

## Roadmap (priority order)

### Phase 1 — Baseline freeze ✅

This document. Policy engine frozen at `hold_baseline_policy`.

### Phase 2 — WebSocket reliability

Fix `agent/data/delta_client.py` concurrent `recv()` issue.

Acceptance criteria:

- No concurrent `recv()` exceptions during extended runtime
- Stable log retention
- No increase in REST fallback frequency
- No regression in telemetry generation

### Phase 3 — Continuous validation pipeline

Run daily via `tools/commands/rolling_validation.py`:

```
Collect telemetry → 7d/30d replay → regime report → compare baseline → archive
```

Outputs: `data/investigation/rolling/YYYY-MM-DD/`

### Phase 4 — Signal quality program

1. Calibration (reliability curves, Brier, ECE)
2. Feature quality (importance, drift, ablation)
3. Regime quality (classifier accuracy, transition stability)
4. Thesis quality (`hypothesis_no_rule_fired` root cause)

### Phase 5 — Weekly dashboard

Track per week: ML candidates, policy HOLD %, executions, replay EV, shadow EV,
win rate, regime mix, confidence calibration.

---

## Archived artifacts

- [`forensic_report_2026-07-11.md`](forensic_report_2026-07-11.md)
- [`promotion_gate_evaluation_2026-07-11.md`](promotion_gate_evaluation_2026-07-11.md)
- [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json)
- [`counterfactual_replay_7d.json`](counterfactual_replay_7d.json)
- [`counterfactual_replay_30d.json`](counterfactual_replay_30d.json)
- [`directional_stability_2026-07-11.json`](directional_stability_2026-07-11.json)
- [`shadow_forward_runbook.md`](shadow_forward_runbook.md)

---

## Next actions

1. Redeploy agent after WebSocket fix
2. Schedule daily `rolling_validation.py` (Task Scheduler / cron)
3. Continue `LATENT_SHADOW_MODE=true` for 48h–1 week minimum
4. Re-open policy discussion only when Phase 3–4 evidence contradicts baseline
