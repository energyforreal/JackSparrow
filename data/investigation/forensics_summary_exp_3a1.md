# Forensics Summary — Exp 3A.1 (Hypothesis Investigation)

**Window:** 48h agent log (`agent_forensics_2026-07-09.log`)  
**Config:** Baseline (no strategy flags changed)  
**Generated:** 2026-07-09

## Key metrics

| Metric | Value |
|--------|-------|
| hold_at_synthesis | 283 (94.65%) |
| v15_adx_trending_filter | 16 (5.35%) |
| risk_approved / fills | 0 / 0 |
| v43 collapse rate | ~99.48% |

## Hypothesis buckets

| Bucket | Count | % | Meaning |
|--------|------:|--:|---------|
| B4 | 283 | 100% | v43 gates passed, policy HOLD, flat hypothesis |
| B1 | 0 | 0% | Selector removed all profiles |
| B2 | 0 | 0% | Zero weighted pressure |
| B3 | 0 | 0% | Margin below min |
| A | 0 | 0% | Shadow agrees, genuine no-setup |

## Shadow analysis

- Shadow agrees with live HOLD: 283 (100%)
- `would_block_live_entry`: 0
- Shadow disagrees: 0

## Gate outcome

**Decision:** `proceed_3a2`

All holds are policy blocks on flat hypothesis while v43 gates passed. Upstream B1/B2 path is not the dominant cause in this window.

## Artifacts

- `hypothesis_breakdown_2026-07-09.json`
- `phase3_gate_decision_3a1.md`
- `rejection_forensics_2026-07-09.json`

## Next step

Enable isolated 3A.2 testnet with `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true` only.
