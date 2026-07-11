# Shadow Disagreement Validation — 2026-07-11

**Window:** 12h pre-forward-shadow baseline  
**Source:** `shadow_eval_report.json` + `counterfactual_replay_2026-07-11.json`

## Summary

| Metric | Value |
|--------|-------|
| Agreement rate | 97.8% |
| Disagreements | 12 rows (4 unique policy LONG cycles) |
| Pattern | Policy LONG → Shadow HOLD |
| Realized EV (no_adx scenario) | **-0.21%** on 4 trades |
| G6 pre-check | **FAIL** (negative realized EV on shadow-only entries) |

## Interpretation

Shadow disagreements in the 12h window correspond to the 4 policy-approved LONGs blocked by ADX (`v15_adx_trending_filter`). Counterfactual replay labels those 4 with negative realized forward return after fees.

Forward shadow collection (`LATENT_SHADOW_MODE=true`) started **2026-07-11** after agent recreate. Full G6 requires 48–72h OOS window per [`shadow_forward_runbook.md`](shadow_forward_runbook.md).

## Collection status

- Agent recreated with `LATENT_SHADOW_MODE=true`
- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false` (unchanged)
- Re-evaluate G6 after: `python tools/commands/shadow_eval.py --hours 48`
