# Counterfactual Replay Report

Generated: 2026-07-11T12:31:03.659880+00:00
Window hours: 720.0
Candidates labeled: 2299

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 374 | 7.22 | 0.024 | -0.2 | 3.7397 | 18.7 | 2.0 |
| ml_adopt_flat | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_adopt_flat_score50 | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_only | 2299 | 3.0 | 0.014 | -0.2027 | 23.3025 | 114.95 | 2.0 |
| no_adx | 378 | 7.14 | 0.024 | -0.2001 | 3.7816 | 18.9 | 2.0 |
| no_thesis_veto | 2299 | 3.0 | 0.014 | -0.2027 | 23.3025 | 114.95 | 2.0 |

## Directional stability

- **sample_count**: 2299
- **flip_rate**: 0.0701
- **mean_run_length**: 14.19
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1244, 'SHORT': 1055}
- **directional_entropy**: 0.9951

| Transition | Count |
|------------|------:|
| LONG->LONG | 1163 |
| LONG->SHORT | 81 |
| SHORT->LONG | 80 |
| SHORT->SHORT | 974 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: PASS (value=167, threshold=30)
- G2_net_ev: FAIL (value=-0.2099, threshold=> 0)
- G3_max_dd: PASS (value=1.7527, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0701, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 2088 | 2.2 | -0.2038 |
| 50 | 167 | 2.4 | -0.2099 |
| 55 | 167 | 2.4 | -0.2099 |
| 60 | 167 | 2.4 | -0.2099 |