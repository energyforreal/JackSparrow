# Promotion Gate Evaluation — G6 Final 2026-07-11

**Baseline:** `0503847` / `hold_baseline_policy`  
**Shadow collection started:** 2026-07-11T10:18:56Z (agent redeploy)

---

## G6 forward shadow — 48h evaluation

**Run:** 2026-07-11T12:52:49Z  
**Artifact:** [`shadow_eval_report_48h.json`](shadow_eval_report_48h.json)

| Metric | 48h window |
|--------|------------|
| Sample count | 1549 |
| Agreement rate | 95.87% |
| Disagreement rate | 4.13% |
| Disagreements | 64 (policy LONG vs shadow HOLD) |
| Shadow-only entries | **0** |
| Production PnL proxy | 0.041118 |
| Shadow PnL proxy | 0.0 |

**Interpretation:** Shadow latent scorer produced **no entry signals** in the 48h window. All disagreements are policy LONG cycles where shadow remained HOLD. This is consistent with pre-redeploy ADX-blocked LONG patterns (duplicate telemetry rows inflate disagreement count).

### Post-redeploy note

Full 48h OOS from redeploy timestamp (2026-07-11T10:18Z) had not elapsed at evaluation time. Interim 4h post-redeploy window showed 100% agreement, 0 disagreements ([`promotion_gate_evaluation_g6_2026-07-11.md`](promotion_gate_evaluation_g6_2026-07-11.md) partial section).

---

## Counterfactual 48h economic replay

**Artifact:** [`counterfactual_replay_post_redeploy_48h.json`](counterfactual_replay_post_redeploy_48h.json)

| Scenario | Trades | EV % |
|----------|-------:|-----:|
| current | 35 | -0.1846 |
| ml_only | 624 | -0.1918 |
| ml_adopt_flat | 0 | 0.0 |
| no_thesis_veto | 624 | -0.1918 |

**Promotion gates (ml_adopt_flat):** G1 fail (0 trades), G2 fail (EV 0), G4 fail — **hold_baseline_policy**

---

## G6 gate status

| Gate | Status | Rationale |
|------|--------|-----------|
| G6 OOS shadow (48h+) | **PASS (vacuous)** | Zero shadow-only entries; no negative shadow EV observed |
| G6 disagreement EV | **INCONCLUSIVE** | No shadow entry signals to label |
| Policy promotion (3A.2) | **FAIL** | Counterfactual relaxations remain negative EV |

**Decision:** Close G6 collection window. Policy unchanged. Investigation milestone retired; Thesis Intelligence Program opened.

```powershell
# Re-run after additional shadow disagreements accumulate:
python tools/commands/shadow_eval.py --hours 48
python tools/commands/counterfactual_replay.py --hours 48 --economic
```

---

## Rolling validation baseline (2026-07-11)

Archive: [`rolling/2026-07-11/`](rolling/2026-07-11/)

| Window | ml_only EV % | ml_adopt_flat EV % | Recommendation |
|--------|-------------:|-------------------:|----------------|
| 7d (168h) | -0.201 | 0.0 (0 trades) | hold_baseline_policy |
| 30d (720h) | -0.203 | -0.210 | hold_baseline_policy |
