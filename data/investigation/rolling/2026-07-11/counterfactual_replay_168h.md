# Counterfactual Replay Report

Generated: 2026-07-11T12:29:04.716269+00:00
Window hours: 168.0
Candidates labeled: 2084

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 191 | 12.04 | 0.044 | -0.1873 | 1.7883 | 9.55 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2084 | 3.17 | 0.019 | -0.201 | 21.0164 | 104.2 | 2.0 |
| no_adx | 195 | 11.79 | 0.043 | -0.1877 | 1.8302 | 9.75 | 2.0 |
| no_thesis_veto | 2084 | 3.17 | 0.019 | -0.201 | 21.0164 | 104.2 | 2.0 |

## Directional stability

- **sample_count**: 2084
- **flip_rate**: 0.061
- **mean_run_length**: 16.28
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1105, 'SHORT': 979}
- **directional_entropy**: 0.9974

| Transition | Count |
|------------|------:|
| LONG->LONG | 1041 |
| LONG->SHORT | 64 |
| SHORT->LONG | 63 |
| SHORT->SHORT | 915 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.061, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1889 | 2.28 | -0.2023 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |