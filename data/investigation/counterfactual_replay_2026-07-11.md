# Counterfactual Replay Report

Generated: 2026-07-11T16:38:07.122293+00:00
Window hours: 168.0
Candidates labeled: 2098

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 198 | 11.62 | 0.042 | -0.19 | 1.8808 | 9.9 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2098 | 3.24 | 0.023 | -0.1999 | 21.1163 | 104.9 | 2.0 |
| no_adx | 203 | 11.33 | 0.041 | -0.1904 | 1.9329 | 10.15 | 2.0 |
| no_thesis_veto | 2098 | 3.24 | 0.023 | -0.1999 | 21.1163 | 104.9 | 2.0 |
| neutral_mild_trend | 0 | None | None | 0.0 | 0.0 | 0.0 | None |

## Directional stability

- **sample_count**: 2098
- **flip_rate**: 0.0596
- **mean_run_length**: 16.65
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1097, 'SHORT': 1001}
- **directional_entropy**: 0.9985

| Transition | Count |
|------------|------:|
| LONG->LONG | 1034 |
| LONG->SHORT | 63 |
| SHORT->LONG | 62 |
| SHORT->SHORT | 938 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0596, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1895 | 2.37 | -0.2009 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |