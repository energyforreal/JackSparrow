# Counterfactual Replay Report

Generated: 2026-07-12T10:33:48.386296+00:00
Window hours: 720.0
Candidates labeled: 2657

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 395 | 6.84 | 0.023 | -0.2004 | 3.9577 | 19.75 | 2.0 |
| ml_adopt_flat | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_adopt_flat_score50 | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_only | 2657 | 2.67 | 0.014 | -0.2022 | 26.8955 | 132.85 | 2.0 |
| no_adx | 422 | 6.4 | 0.021 | -0.2001 | 4.2228 | 21.1 | 2.0 |
| no_thesis_veto | 2657 | 2.67 | 0.014 | -0.2022 | 26.8955 | 132.85 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 2657
- **flip_rate**: 0.0666
- **mean_run_length**: 14.93
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1407, 'SHORT': 1250}
- **directional_entropy**: 0.9975

| Transition | Count |
|------------|------:|
| LONG->LONG | 1318 |
| LONG->SHORT | 89 |
| SHORT->LONG | 88 |
| SHORT->SHORT | 1161 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: PASS (value=167, threshold=30)
- G2_net_ev: FAIL (value=-0.2099, threshold=> 0)
- G3_max_dd: PASS (value=1.7527, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0666, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 2400 | 1.96 | -0.2035 |
| 50 | 167 | 2.4 | -0.2099 |
| 55 | 167 | 2.4 | -0.2099 |
| 60 | 167 | 2.4 | -0.2099 |