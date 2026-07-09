# Forensics Summary — Exp 3B (Thesis-Aware ADX Testnet)

**Status:** BLOCKED — economic replay gate not passed  
**Flag:** `V15_ADX_THESIS_AWARE_ENABLED=true` (only when unblocked)

## Economic replay gate (pre-testnet)

**Artifact:** `economic_replay_2026-07-09.json`

| Requirement | Required | Observed | Pass? |
|-------------|----------|----------|-------|
| Net expectancy after fees | Positive | -0.2504% avg | No |
| Sample size (ADX cohort) | n ≥ 30 | n = 16 | No |
| Promotion blocked | — | true | — |

**Do not start 3B testnet** until log window expanded and net expectancy is positive on replay.

## Pre-run checklist (when unblocked)

- [ ] 3A.2 flag **off** (or rolled back)
- [ ] `V15_ADX_THESIS_AWARE_ENABLED=true` only
- [ ] Economic replay re-run with n ≥ 30 and positive net expectancy
- [ ] Record experiment start timestamp

## Daily commands

```powershell
python tools/commands/phase3_daily_forensics.py --workstream 3b
python tools/commands/forensics_economic_replay.py <log> --reject-reason v15_adx_trending_filter
```

## Rollback triggers

- ADX rejects decrease but economic replay net < 0
- Mean-reversion cohort regresses in replay
- Live slippage p95 worsens vs baseline stat audit

**Rollback:** `V15_ADX_THESIS_AWARE_ENABLED=false`

## Post-run artifacts (to generate)

- `agent_exp_3b_<date>.log`
- `economic_replay_<date>.json`
- `forensics_summary_exp_3b_results.md` (fill metrics after run)
