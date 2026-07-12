# Attribution + next experiment (updated post funnel day1)

**As-of:** 2026-07-12 T+3h Phase A ([`scorecard_day1.md`](scorecard_day1.md), [`funnel_post_a.json`](funnel_post_a.json))  
**Prior day0 tree:** superseded for post-A slice only.

## Post-A miss mix (layered funnel)

| Research / admission layer | Count | Share of thesis fires |
|----------------------------|------:|----------------------:|
| Thesis fires (trend_continuation SHORT) | 15 | 100% of fires |
| Quality below floor (~46 &lt; 55) | 15 | **100%** |
| Gate5 fail | 15 | **100%** |
| HOLD after thesis fire | 15 | **100%** |
| Flat hyp as primary (post-A fires) | 0 among fires | — |
| Risk veto | 0 | 0% |
| ADX handler (this funnel) | — | not dominant on fire path |

Endpoint (no single research miss &gt;40% of *missed opportunities*): **not met** for fills — admission layers dominate. Flat-hyp is **no longer** the binding research miss on cycles where hurst_v2 thesis fires.

## Decision tree application

| Branch condition | Fired? | Action |
|------------------|--------|--------|
| Still flat hyp ≥40% and trend fire improved but policy blocks ML | Flat hyp **no longer** binding on fire cycles; trend fire **improved** | Stay on **A**; do **not** enable B |
| ADX becomes largest costly miss | No on fire path | Keep C offline; **no live 3B** |
| Quality floors dominate | **Yes** (100% of fires) | Design **offline** quality/Gate5 CF when n≥30; **no live floor change** |
| Mix diversified & EV/DD OK | No fills yet | Skip promote |
| A fails EV or kill | No | Keep A |

## Chosen next step (now)

1. **Primary:** Continue live **Phase A** through T+48–72h; daily funnel + `scorecard_dayN`.  
2. **Do not** lower `ENTRY_QUALITY` / trade-score floor or Gate5 ratio in `.env`.  
3. **Offline CF gate:** when post-A funnel shows **n≥30** thesis fires blocked at quality (scores ~45–54) and/or Gate5 near-misses, run offline counterfactual under `data/investigation/` only.  
4. **Current n:** quality/Gate5 blocked fires = **15 &lt; 30** → offline CF **deferred**.  
5. Secondary candidates (mild_trend / ADX 3B / vol) remain blocked per [`../../secondary_candidates_verdict_2026-07-12.md`](../../secondary_candidates_verdict_2026-07-12.md).

## Explicit non-auto-advance

**Not** enabling:

- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`
- `V15_ADX_THESIS_AWARE_ENABLED`
- `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED`
- Any quality floor / Gate5 ratio production change
