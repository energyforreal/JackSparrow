# Counterfactual Replay Report

Generated: 2026-07-11T16:34:20.369988+00:00
Window hours: 720.0
Candidates labeled: 2363

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 383 | 7.05 | 0.023 | -0.2009 | 3.8477 | 19.15 | 2.0 |
| ml_adopt_flat | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_adopt_flat_score50 | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_only | 2363 | 3.0 | 0.017 | -0.2018 | 23.9182 | 118.15 | 2.0 |
| no_adx | 388 | 6.96 | 0.023 | -0.201 | 3.8999 | 19.4 | 2.0 |
| no_thesis_veto | 2363 | 3.0 | 0.017 | -0.2018 | 23.9182 | 118.15 | 2.0 |
| neutral_mild_trend | 0 | None | None | 0.0 | 0.0 | 0.0 | None |

## Directional stability

- **sample_count**: 2363
- **flip_rate**: 0.069
- **mean_run_length**: 14.41
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1285, 'SHORT': 1078}
- **directional_entropy**: 0.9945

| Transition | Count |
|------------|------:|
| LONG->LONG | 1203 |
| LONG->SHORT | 82 |
| SHORT->LONG | 81 |
| SHORT->SHORT | 996 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: PASS (value=167, threshold=30)
- G2_net_ev: FAIL (value=-0.2099, threshold=> 0)
- G3_max_dd: PASS (value=1.7527, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.069, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 2142 | 2.24 | -0.2026 |
| 50 | 167 | 2.4 | -0.2099 |
| 55 | 167 | 2.4 | -0.2099 |
| 60 | 167 | 2.4 | -0.2099 |