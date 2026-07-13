# Counterfactual Replay Report

Generated: 2026-07-13T06:03:38.285905+00:00
Window hours: 168.0
Candidates labeled: 2348

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 193 | 12.44 | 0.044 | -0.191 | 1.8427 | 9.65 | 2.01 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2348 | 3.15 | 0.017 | -0.2043 | 23.9873 | 117.4 | 2.0 |
| no_adx | 222 | 10.81 | 0.038 | -0.1917 | 2.1279 | 11.1 | 2.0 |
| no_thesis_veto | 2348 | 3.15 | 0.017 | -0.2043 | 23.9873 | 117.4 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 2348
- **flip_rate**: 0.055
- **mean_run_length**: 18.06
- **max_run_length**: 118
- **direction_counts**: {'SHORT': 1154, 'LONG': 1194}
- **directional_entropy**: 0.9998

| Transition | Count |
|------------|------:|
| LONG->LONG | 1129 |
| LONG->SHORT | 64 |
| SHORT->LONG | 65 |
| SHORT->SHORT | 1089 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.055, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 2007 | 2.24 | -0.2043 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |