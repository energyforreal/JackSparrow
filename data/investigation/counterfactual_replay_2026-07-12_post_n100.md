# Counterfactual Replay Report

Generated: 2026-07-12T12:52:21.540526+00:00
Window hours: 168.0
Candidates labeled: 2100

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 188 | 12.23 | 0.044 | -0.1911 | 1.7968 | 9.4 | 2.01 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2100 | 3.14 | 0.017 | -0.2016 | 21.2001 | 105.0 | 2.0 |
| no_adx | 215 | 10.7 | 0.038 | -0.1918 | 2.0619 | 10.75 | 2.0 |
| no_thesis_veto | 2100 | 3.14 | 0.017 | -0.2016 | 21.2001 | 105.0 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 2100
- **flip_rate**: 0.0567
- **mean_run_length**: 17.5
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1106, 'SHORT': 994}
- **directional_entropy**: 0.9979

| Transition | Count |
|------------|------:|
| LONG->LONG | 1046 |
| LONG->SHORT | 60 |
| SHORT->LONG | 59 |
| SHORT->SHORT | 934 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0567, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1873 | 2.24 | -0.2033 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |