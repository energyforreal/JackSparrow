# Phase A gate — provisional (window incomplete)

**Evaluated:** 2026-07-12 ~T+1h after enable (plan requires **T+48–72h**)  
**Decision:** **CONTINUE** — neither promote nor rollback

## Kill criteria

| Criterion | Status |
|-----------|--------|
| Agent unhealthy | PASS (healthy) |
| WS error loop | PASS (single clean_close warn at recreate) |
| Risk veto spike >15% | PASS (0) |
| G1 collapse >15% w/o thesis benefit | PASS / insufficient N |
| Unexplained handler failure | PASS |

## Promote criteria (all required)

| Criterion | Status |
|-----------|--------|
| Replay EV ≥ baseline | **DEFERRED** (rolling economic not run in day0; CF recommends hold_baseline) |
| Testnet EV ≥ baseline | **DEFERRED** (0 fills post-A) |
| DD ≤ tolerance | **DEFERRED** |
| Trend fire ≥2× or ≥5/24h | **FAIL so far / insufficient post-A N** |
| Neg controls stable | **OK so far** |
| Ops healthy | **PASS** |

## Action

1. Keep `AGENT_THESIS_USE_HURST_V2=true`.  
2. Re-evaluate at **T+48h** (2026-07-14 ~10:21 UTC) and **T+72h** with full scorecard + economic rolling if needed.  
3. Rollback only if kill criteria trip or final window EV fails.

Scheduled gate file to update: `A_GATE_FINAL.md` after window.
