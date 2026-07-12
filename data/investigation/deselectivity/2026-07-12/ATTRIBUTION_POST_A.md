# Attribution + next bottleneck — post-A funnel (2026-07-12 T+3h)

**Supersedes day0 tree timing in** [`ATTRIBUTION_NEXT.md`](ATTRIBUTION_NEXT.md) **for post-A cycles only.**  
**Flags unchanged:** hurst_v2 on; flat-hyp ML / ADX thesis-aware / mild-trend **off**.

## Post-A miss mix (thesis-fire cohort)

From [`funnel_post_a.json`](funnel_post_a.json) since Phase A start:

| Layer | Count | Share of thesis fires |
|-------|------:|----------------------:|
| Thesis fires (`trend_continuation` SHORT) | 15 | 100% |
| Quality below floor (mean score ≈46 &lt; 55) | 15 | **100%** |
| Gate5 fail | 15 | **100%** |
| HOLD after thesis fire | 15 | **100%** |
| Risk veto | 0 | 0% |
| Flat hyp as fire blocker | — | **not binding** on this cohort |

Pre-A calendar-day mix may still show high `hypothesis_no_rule_fired`; **post-A opportunity path has shifted**.

## Decision tree (updated)

| Branch condition | Fired? | Action |
|------------------|--------|--------|
| Flat hyp ≥40% of *post-A* research misses | **No** for fired-thesis path | Do not design B from this cohort |
| Quality floors dominate entry holds | **Yes** (100% of fires) | Next research target after A window — **offline only** |
| Gate5 dominates | **Yes** (co-binding with quality) | Same — joint offline CF after n≥30 |
| ADX costly with n≥30 EV≥0 | No (still n≈10, EV&lt;0) | Keep C offline accumulate |
| A fails EV or kill | No | Stay on A |

## Offline CF gate (do not run live threshold changes)

Only when funnel shows **n≥30** thesis fires blocked at quality (~45–54) and/or Gate5 near-misses **and** A_GATE T+48/72 allows research:

1. Offline counterfactual: quality floor 55→50 and/or Gate5 ratio — document under `data/investigation/`.  
2. Floors stay frozen in `.env` until full Context promotion gate (EV≥0, DD≤5%, regime, approval vs `0503847`).

**Current n=15 thesis fires** → offline CF **deferred** (below n≥30).

## Chosen next step (now)

1. Continue Phase A through T+48h / T+72h.  
2. Daily funnel scorecards.  
3. No B/C/D flag enables. No floor/ratio edits.
