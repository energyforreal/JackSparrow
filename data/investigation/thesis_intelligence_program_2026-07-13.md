# Thesis Intelligence Program — 2026-07-13

**Status:** Active  
**Predecessor:** Signal Quality & Continuous Validation (retired)  
**Baseline:** commit `0503847` / `hold_baseline_policy`

---

## Objective

Improve **structural hypothesis generation** so thesis and ML converge **where replay shows positive expectancy**. This is not a trade-count optimization program.

---

## Investigation outcome (inherited)

| Finding | Status |
|---------|--------|
| Infrastructure healthy | Confirmed |
| Policy thesis fusion drives abstention | Confirmed |
| Policy relaxation improves EV | **Falsified** (negative replay EV) |
| Dominant pattern: B4 bucket | 96.3% of holds (prior window) |
| G6 shadow 48h | Closed — vacuous pass (0 shadow entries) |

See [`investigation_closure_2026-07-11.md`](investigation_closure_2026-07-11.md) and [`promotion_gate_evaluation_g6_2026-07-11.md`](promotion_gate_evaluation_g6_2026-07-11.md).

---

## Scope

### In scope

1. Thesis rule miss diagnostics (`thesis_rule_miss_analysis.py`)
2. Decision Quality Index (`decision_quality_index.py`)
3. Neutral-regime rule coverage research
4. Threshold calibration **via shadow + replay** (never direct production change)
5. Replay-label calibration proxy (`build_calibration_dataset.py --replay-json`)
6. Weekly rolling validation + DQI trend

### Explicit non-goals

- Enable `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` (3A.2)
- Lower `AGENT_TRADE_SCORE_MIN`
- Disable ADX trending filter
- Global thesis gating relaxation without governance pass

---

## Governance (unchanged)

Every policy or thesis rule promotion requires **all** of:

1. Rolling replay (7d + 30d) positive net EV for **current** scenario
2. Forward shadow (G6) non-negative realized EV over 48h+ OOS
3. Regime-stratified validation
4. Promotion gate review in `data/investigation/`
5. Explicit approval against baseline `0503847`

---

## Engineering artifacts

| Artifact | Path |
|----------|------|
| Rule miss diagnostics | [`tools/commands/thesis_rule_miss_analysis.py`](../../tools/commands/thesis_rule_miss_analysis.py) |
| Decision Quality Index | [`tools/commands/decision_quality_index.py`](../../tools/commands/decision_quality_index.py) |
| Thesis diagnose API | [`agent/core/agent_thesis_engine.py`](../../agent/core/agent_thesis_engine.py) — `diagnose_rule_miss()`, `nearest_rule_miss()` |
| Neutral mild trend prototype | `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED=false` (default) |
| Replay calibration | [`calibration_dataset_replay_2026-07-11.json`](calibration_dataset_replay_2026-07-11.json) |
| Baseline DQI | [`dqi_2026-07-11.json`](dqi_2026-07-11.json) — composite **50.52** |

---

## Success metrics (8-week horizon)

| Metric | Baseline (2026-07-11) | Target |
|--------|----------------------|--------|
| B4 bucket % | 96.3% | Decrease with evidence |
| B4 rate (ML-pass cycles) | 89.2% | Identify + reduce dominant miss |
| Replay EV (current, 7d) | -0.187% | Non-worsening; positive in target sub-regime |
| DQI composite | 50.52 | Week-over-week trend documented |
| Production executions | 0 | Not a target |

---

## Operational cadence

| Cadence | Command |
|---------|---------|
| Daily | `scripts/daily_validation.ps1` |
| Weekly | `scripts/daily_validation.ps1 -Weekly` |
| On thesis change | Full governance stack + unit tests |

---

## Phase roadmap

1. **Diagnostics** — thesis rule miss analysis + memo ([`thesis_rule_miss_2026-07-11.md`](thesis_rule_miss_2026-07-11.md))
2. **DQI v1** — baseline snapshot + weekly trend
3. **Thesis engineering** — prototype rules behind flags; validate via replay
4. **Calibration** — replay-label proxy active (N=12814); wire into DQI when promoted

---

## Related documents

- [`thesis_interpretation_2026-07-11.md`](thesis_interpretation_2026-07-11.md)
- [`forensic_report_2026-07-11.md`](forensic_report_2026-07-11.md)
- [`shadow_forward_runbook.md`](shadow_forward_runbook.md)
- [`weekly_review_2026-07-11.md`](weekly_review_2026-07-11.md)
