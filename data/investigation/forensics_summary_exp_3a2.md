# Forensics Summary — Exp 3A.2 (Policy Semantics Testnet)

**Status:** Protocol ready — awaiting 48–72h isolated testnet run  
**Flag:** `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true` (only active strategy change)

## Pre-run checklist

- [ ] 3A.2 flag enabled in agent env
- [ ] `V15_ADX_THESIS_AWARE_ENABLED=false`
- [ ] `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` is the **only** strategy flag changed
- [ ] Record experiment start timestamp

## Daily commands

```powershell
python tools/commands/phase3_daily_forensics.py --workstream 3a2
```

## Promotion criteria (fill after run)

| Metric | Baseline | Observed | Pass? |
|--------|----------|----------|-------|
| risk_approved_count | 0 | _TBD_ | |
| hold_at_synthesis rate | 94.7% | _TBD_ | |
| Net expectancy (new fills) | -$0.85 | _TBD_ | |
| Fee-dominated loss share | from stat audit | _TBD_ | |
| Collapse rate | 99.48% | _TBD_ | |

## Rollback triggers

- HOLD rate drops but expectancy worsens vs baseline
- risk_approved increases but fill_count stays flat
- Fee-dominated closes increase >20% relative to baseline
- Orphan risk approvals (reconcile tool fails)

**Rollback:** `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=false`

## Post-run artifacts (to generate)

- `agent_exp_3a2_<date>.log`
- `rejection_forensics_<date>.json`
- `hypothesis_breakdown_<date>.json`
- `strategy_stat_audit` for experiment window
