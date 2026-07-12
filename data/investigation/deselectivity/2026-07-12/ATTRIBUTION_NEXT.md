# Attribution + next experiment (provisional decision tree)

**As-of:** day0 / early Phase A (post-A N still tiny; full-day mix mostly pre-A)

## Current miss mix (day0 forensics)

| Research-layer miss | Share |
|---------------------|------:|
| Flat hyp / `hypothesis_no_rule_fired` → hold_at_synthesis | **90.4%** |
| ADX trending filter | **9.6%** |
| Quality / conviction / EMA / BB as primary | ~0% in handler histogram |

Endpoint (no single research miss >40%): **not met** (flat hyp still ~90%).

## Decision tree application

| Branch condition | Fired? | Action |
|------------------|--------|--------|
| Still flat hyp ≥40% and trend fire improved but policy blocks ML | Flat hyp yes; **trend fire not yet proven** | Stay on **A**; prep B offline only |
| ADX becomes largest costly miss | No (9.6%, EV negative) | Continue **C offline** accumulate n; **no live 3B** |
| Quality floors dominate | No | Skip D |
| Mix diversified & EV/DD OK | No | Skip F |
| A fails EV or kill | No | Keep A |

## Chosen next step (now)

1. **Primary:** Continue live **Phase A** through 48–72h; daily `scorecard_dayN`.  
2. **Parallel:** Keep building B/C offline evidence (`OFFLINE_BC.md`) — **do not enable B or C flags**.  
3. **After A window:** Re-run this tree on **post-A-only** attribution. If trend fire improved and flat hyp still ≥40% with costly CF EV≥0, design B; if ADX share/cost dominates with n≥30 EV≥0, design C.

## Explicit non-auto-advance

**Not** enabling `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` or `V15_ADX_THESIS_AWARE_ENABLED` at this time.
