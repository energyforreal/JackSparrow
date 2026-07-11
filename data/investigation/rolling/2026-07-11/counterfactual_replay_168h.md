# Counterfactual Replay Report

Generated: 2026-07-11T16:32:17.044562+00:00
Window hours: 168.0
Candidates labeled: 2094

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 198 | 11.62 | 0.042 | -0.19 | 1.8808 | 9.9 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2094 | 3.15 | 0.016 | -0.2015 | 21.0927 | 104.7 | 2.0 |
| no_adx | 203 | 11.33 | 0.041 | -0.1904 | 1.9329 | 10.15 | 2.0 |
| no_thesis_veto | 2094 | 3.15 | 0.016 | -0.2015 | 21.0927 | 104.7 | 2.0 |
| neutral_mild_trend | 0 | None | None | 0.0 | 0.0 | 0.0 | None |

## Directional stability

- **sample_count**: 2094
- **flip_rate**: 0.0597
- **mean_run_length**: 16.62
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1097, 'SHORT': 997}
- **directional_entropy**: 0.9984

| Transition | Count |
|------------|------:|
| LONG->LONG | 1034 |
| LONG->SHORT | 63 |
| SHORT->LONG | 62 |
| SHORT->SHORT | 934 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0597, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1891 | 2.27 | -0.2026 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |