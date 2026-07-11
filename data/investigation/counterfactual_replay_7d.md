# Counterfactual Replay Report

Generated: 2026-07-11T07:53:41.380789+00:00
Window hours: 168.0
Candidates labeled: 2060

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 191 | 12.04 | 0.044 | -0.1873 | 1.7883 | 9.55 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2060 | 3.2 | 0.019 | -0.2012 | 20.7972 | 103.0 | 2.0 |
| no_adx | 195 | 11.79 | 0.043 | -0.1877 | 1.8302 | 9.75 | 2.0 |
| no_thesis_veto | 2060 | 3.2 | 0.019 | -0.2012 | 20.7972 | 103.0 | 2.0 |

## Directional stability

- **sample_count**: 2060
- **flip_rate**: 0.0602
- **mean_run_length**: 16.48
- **max_run_length**: 118
- **direction_counts**: {'SHORT': 957, 'LONG': 1103}
- **directional_entropy**: 0.9964

| Transition | Count |
|------------|------:|
| LONG->LONG | 1041 |
| LONG->SHORT | 62 |
| SHORT->LONG | 62 |
| SHORT->SHORT | 894 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0602, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1865 | 2.31 | -0.2026 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |