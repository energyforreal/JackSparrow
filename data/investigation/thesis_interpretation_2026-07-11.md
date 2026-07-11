# Thesis Quality Interpretation — 2026-07-11

**Sources:** [`hypothesis_breakdown_2026-07-11.json`](hypothesis_breakdown_2026-07-11.json), [`agent_baseline_2026-07-11.log`](agent_baseline_2026-07-11.log), rejection forensics

## Summary

| Metric | Value |
|--------|------:|
| `hold_at_synthesis` (24h log) | 27 |
| B4 bucket (ML pass, policy HOLD, flat hypothesis) | **96.3%** (26/27) |
| Primary reject code | `hypothesis_no_rule_fired` (100%) |
| Eligible profiles present but unfired | `breakout`, `trend_continuation` |

## Interpretation

**Abstention driver:** The hypothesis engine fires **no rules** in `regime=neutral` while ML v43 gates pass (`gates_passed_long` / `gates_passed_short`). Policy then applies `thesis_blocks_ml_adoption` under `ml_or_thesis` fusion with `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false`.

**Coverage gap vs correct abstention:** Eligible profiles (`breakout`, `trend_continuation`) appear in snapshots but `hypothesis_count=0` and zero long/short pressure — rules are not activating despite structural ML direction. This suggests **thesis rule coverage** in neutral regime may be too narrow, not that policy is accidentally blocking good thesis entries.

**Shadow agreement:** Rule-based shadow agrees with HOLD on 96.3% of holds; no shadow/live disagreements in this window.

**Gate tool note:** `forensics_hypothesis_breakdown` emits `proceed_3a2` when B4 > 30% — that is a **semantic review trigger**, not a promotion recommendation. Counterfactual replay (30d) shows `ml_adopt_flat` EV **-0.21%** — 3A.2 remains **not promoted** per governance.

## Recommended signal-quality focus

1. Inspect [`agent/core/hypothesis_aggregator.py`](../../agent/core/hypothesis_aggregator.py) neutral-regime rule firing conditions
2. Why `trade_score` ~47–48 when ML component is high but `ml_confirms=False` (thesis blocks confirmation)
3. Do not relax policy gates until replay shows positive EV for target scenario

## Artifacts

- [`hypothesis_breakdown_2026-07-11.json`](hypothesis_breakdown_2026-07-11.json)
- [`phase3_gate_decision_3a1.md`](phase3_gate_decision_3a1.md)
- [`ablation_report_2026-07-11.md`](ablation_report_2026-07-11.md)
- [`logs/agent/signal_recovery/attribution_report.json`](../../logs/agent/signal_recovery/attribution_report.json)
