# Forensics Summary — Exp 3A.2 (Policy Semantics Testnet)

**Status:** **BLOCKED** — counterfactual replay shows negative realized EV  
**Date:** 2026-07-11  
**Flag:** `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS=true` — **NOT enabled**

## Counterfactual replay gate evaluation

See [`promotion_gate_evaluation_2026-07-11.md`](promotion_gate_evaluation_2026-07-11.md).

| Gate | 12h | 7d | 30d | Required |
|------|-----|-----|-----|----------|
| G1 sample ≥ 30 | FAIL (0) | FAIL (0) | PASS (167) | PASS |
| G2 net EV > 0 | FAIL | FAIL | **FAIL (-0.21%)** | PASS |
| G3 max DD ≤ 5% | PASS | PASS | PASS | PASS |
| G4 non-ranging EV | FAIL | FAIL | FAIL | PASS |
| G5 flip rate ≤ 0.5 | PASS (0.09) | PASS (0.06) | PASS (0.07) | PASS |
| G6 OOS shadow | **FAIL** (pre-shadow baseline) | — | — | PASS |

**Recommendation:** `hold_baseline_policy`

## Promotion criteria (filled)

| Metric | Baseline | Observed (30d replay) | Pass? |
|--------|----------|----------------------|-------|
| risk_approved_count | 0 | 0 (live) | — |
| hold_at_synthesis rate | ~98% | ~98% (12h) | — |
| Net expectancy (`ml_adopt_flat`) | — | **-0.21%** | **NO** |
| Collapse rate | 99.6% | unchanged | — |

## Decision

**Do not enable 3A.2 testnet.** Realized-label replay demonstrates that gated ML adoption on flat hypothesis would have produced **negative expectancy** over 30 days (167 trades, 2.4% win rate, PF 0.005).

Abstention in the current ranging regime is **supported by evidence**, not merely observational over-gating.

## Rollback

N/A — flag was never enabled.

## Next steps

1. Continue forward shadow collection (`LATENT_SHADOW_MODE=true`) per [`shadow_forward_runbook.md`](shadow_forward_runbook.md)
2. Re-evaluate when market regime shifts (trending bucket shows positive EV in replay)
3. WebSocket recv fix deployed in `delta_client.py` for log observability
