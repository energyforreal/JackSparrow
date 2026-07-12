# Secondary Candidate Verdicts — 2026-07-12 (post N≥100 evidence)

Evidence gate restored: `decision_evidence/2026-07-12` → **high_confidence=289, sweep_gate=PASS**.
Replayed after Task 1 fix. Success metric = EV / sample gates, not trade count.

---

## 1. `neutral_mild_trend` prototype

**Command:** `python tools/commands/counterfactual_replay.py --hours 168 --economic`  
**Artifact:** [`counterfactual_replay_2026-07-12_post_n100.md`](counterfactual_replay_2026-07-12_post_n100.md)

| Metric | Value | Gate |
|--------|------:|------|
| trades (n) | **5** | need ≥30 → **FAIL** |
| EV % | **−0.2311** | need ≥0 → **FAIL** |
| Max DD % | 0.0578 | ≤5 OK |

**Verdict:** **Still blocked.** Do not enable `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED`. Recommendation remains `hold_baseline_policy`.

---

## 2. ADX thesis-aware relaxation (Phase 3B)

**Command:** `forensics_economic_replay.py` on merged reject logs  
**Artifact:** [`economic_replay_adx_2026-07-12_post_n100.json`](economic_replay_adx_2026-07-12_post_n100.json)

| Metric | Value | Gate |
|--------|------:|------|
| ADX cohort n | **10** | need ≥30 → **FAIL** |
| Avg net return % | **−0.2257** | need ≥0 → **FAIL** |
| promotion_blocked | true | — |

**Verdict:** **Still blocked.** Keep `V15_ADX_THESIS_AWARE_ENABLED=false`. Continue accumulating ADX rejects under live Phase A toward n≥30 before re-litigating.

Updated hold note: see also [`phase3b_hold_2026-07-12.md`](phase3b_hold_2026-07-12.md) (prior same conclusion; n still &lt;30).

---

## 3. Breakout `vol_regime` floor

**Command:** `hurst_v2_vol_counterfactual.py`  
**Artifact:** [`hurst_v2_vol_counterfactual_2026-07-12_post_n100.md`](hurst_v2_vol_counterfactual_2026-07-12_post_n100.md)

| Vol min | Breakout long fires | N |
|--------:|--------------------:|--:|
| 1.1 | **0** | 283 |
| 0.9 | **0** | 283 |
| 0.8 | **0** | 283 |

**Verdict:** **Not the binding constraint — deprioritize.** Do not relax the breakout vol floor in production. Offline hurst_v2 trend shorts did fire (62) on dual-write rows; breakout path still shows 0 fires even at 0.8.

---

## Summary

| Candidate | Decision |
|-----------|----------|
| neutral_mild_trend | Still blocked (n=5, EV&lt;0) |
| ADX Phase 3B | Still blocked (n=10, EV&lt;0) |
| vol_regime floor | Not binding; deprioritize |
| hurst_v2 (Task 3/4) | Continue Phase A testnet only — see [`hurst_v2_historical_backtest_conclusion_2026-07-12.md`](hurst_v2_historical_backtest_conclusion_2026-07-12.md) |
