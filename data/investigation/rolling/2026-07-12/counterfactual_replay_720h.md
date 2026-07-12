# Counterfactual Replay Report

Generated: 2026-07-12T06:04:32.124219+00:00
Window hours: 720.0
Candidates labeled: 1206

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 273 | 7.69 | 0.027 | -0.2039 | 2.7829 | 13.65 | 2.0 |
| ml_adopt_flat | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_adopt_flat_score50 | 167 | 2.4 | 0.005 | -0.2099 | 1.7527 | 8.35 | 2.0 |
| ml_only | 1206 | 2.99 | 0.016 | -0.2123 | 12.7996 | 60.3 | 2.0 |
| no_adx | 273 | 7.69 | 0.027 | -0.2039 | 2.7829 | 13.65 | 2.0 |
| no_thesis_veto | 1206 | 2.99 | 0.016 | -0.2123 | 12.7996 | 60.3 | 2.0 |
| neutral_mild_trend | 0 | None | None | 0.0 | 0.0 | 0.0 | None |

## Directional stability

- **sample_count**: 2582
- **flip_rate**: 0.0666
- **mean_run_length**: 14.92
- **max_run_length**: 118
- **direction_counts**: {'LONG': 1373, 'SHORT': 1209}
- **directional_entropy**: 0.9971

| Transition | Count |
|------------|------:|
| LONG->LONG | 1286 |
| LONG->SHORT | 86 |
| SHORT->LONG | 86 |
| SHORT->SHORT | 1123 |

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
| 45 | 1100 | 1.73 | -0.214 |
| 50 | 167 | 2.4 | -0.2099 |
| 55 | 167 | 2.4 | -0.2099 |
| 60 | 167 | 2.4 | -0.2099 |