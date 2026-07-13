# Counterfactual Replay Report

Generated: 2026-07-13T06:06:10.359919+00:00
Window hours: 720.0
Candidates labeled: 3040

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 403 | 6.95 | 0.023 | -0.1999 | 4.0287 | 20.15 | 2.0 |
| ml_adopt_flat | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_adopt_flat_score50 | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_only | 3040 | 2.6 | 0.013 | -0.2038 | 30.9743 | 152.0 | 2.0 |
| no_adx | 432 | 6.48 | 0.021 | -0.1997 | 4.3139 | 21.6 | 2.0 |
| no_thesis_veto | 3040 | 2.6 | 0.013 | -0.2038 | 30.9743 | 152.0 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 3040
- **flip_rate**: 0.0652
- **mean_run_length**: 15.28
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1571, 'SHORT': 1469}
- **directional_entropy**: 0.9992

| Transition | Count |
|------------|------:|
| LONG->LONG | 1471 |
| LONG->SHORT | 99 |
| SHORT->LONG | 99 |
| SHORT->SHORT | 1370 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: PASS (value=167, threshold=30)
- G2_net_ev: FAIL (value=-0.2099, threshold=> 0)
- G3_max_dd: PASS (value=1.7527, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0652, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 2656 | 1.88 | -0.2037 |
| 50 | 167 | 2.4 | -0.2099 |
| 55 | 167 | 2.4 | -0.2099 |
| 60 | 167 | 2.4 | -0.2099 |