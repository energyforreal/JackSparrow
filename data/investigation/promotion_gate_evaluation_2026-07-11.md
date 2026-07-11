# Promotion Gate Evaluation — 2026-07-11

**Decision:** `hold_baseline_policy` — **do not enable 3A.2 testnet**

Counterfactual replay with realized candle labels was run on 12h, 7d, and 30d windows. All windows fail promotion gates G1–G2 and/or G4 for the `ml_adopt_flat` scenario (the intended 3A.2 behavior).

## Gate results (30d window — largest sample)

| Gate | Threshold | Value | Pass |
|------|-----------|-------|------|
| G1 sample size | ≥ 30 | 167 (`ml_adopt_flat`) | PASS |
| G2 net EV | > 0% | **-0.2099%** | **FAIL** |
| G3 max DD | ≤ 5% | 1.75% | PASS |
| G4 non-ranging EV | positive | false | FAIL |
| G5 flip rate | ≤ 0.5 | 0.069 | PASS |
| G6 OOS shadow | non-negative EV | **FAIL** (12h baseline -0.21%) | **FAIL** |

## Key counterfactual findings

### 12h window (Jul 10–11)

| Scenario | Trades | Win % | EV % | Max DD % |
|----------|--------|-------|------|----------|
| current | 0 | — | 0 | 0 |
| ml_adopt_flat | 0 | — | 0 | 0 |
| ml_only | 182 | 1.65 | **-0.18** | 1.74 |
| no_adx | 4 | 0 | **-0.21** | 0.04 |

- `ml_adopt_flat` = 0 trades in 12h because no flat-thesis cycle had trade_score ≥ 55
- The 4 policy LONGs had thesis=LONG (not flat), blocked by ADX
- ML directional flip rate: **9.4%** (low oscillation — abstention not due to chop flips)

### 30d window

| Scenario | Trades | Win % | EV % | Max DD % |
|----------|--------|-------|------|----------|
| ml_adopt_flat | 167 | 2.4 | **-0.21** | 1.75 |
| ml_only | 2243 | 3.08 | **-0.20** | 22.76 |
| current (observed policy entries) | 374 | 7.22 | **-0.20** | 3.74 |

**Interpretation:** Relaxing thesis veto (`ml_only` / `no_thesis_veto`) would have increased trade volume substantially but with **negative realized expectancy** after fees. Current abstention in ranging chop appears **rational**, not a bug.

## 3A.2 testnet status

`AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` remains **false** (default).

Per [`forensics_summary_exp_3a2.md`](forensics_summary_exp_3a2.md): testnet run **deferred** until replay shows positive EV. Replay shows the opposite.

## Forward shadow (G6)

`LATENT_SHADOW_MODE=true` active in agent (recreated 2026-07-11). Pre-shadow 12h baseline: disagreements map to 4 ADX-blocked LONGs with **-0.21%** realized EV — G6 **FAIL**. See [`shadow_disagreement_validation_2026-07-11.md`](shadow_disagreement_validation_2026-07-11.md). Continue 48–72h collection per [`shadow_forward_runbook.md`](shadow_forward_runbook.md).

## Artifacts

- [`counterfactual_replay_2026-07-11.json`](counterfactual_replay_2026-07-11.json)
- [`counterfactual_replay_7d.json`](counterfactual_replay_7d.json)
- [`counterfactual_replay_30d.json`](counterfactual_replay_30d.json)
- [`directional_stability_2026-07-11.json`](directional_stability_2026-07-11.json)
- [`logs/agent/signal_recovery/ablation_report.json`](../../logs/agent/signal_recovery/ablation_report.json)
