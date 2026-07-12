# Counterfactual Replay Report

Generated: 2026-07-12T10:34:11.245647+00:00
Window hours: 24.0
Candidates labeled: 381

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 21 | 42.86 | 0.789 | -0.0077 | 0.0247 | 1.05 | 2.05 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 381 | 53.81 | 1.038 | 0.0009 | 0.1006 | 19.05 | 2.0 |
| no_adx | 44 | 47.73 | 0.982 | -0.0005 | 0.0315 | 2.2 | 2.02 |
| no_thesis_veto | 381 | 53.81 | 1.038 | 0.0009 | 0.1006 | 19.05 | 2.0 |
| neutral_mild_trend | 5 | 60.0 | 0.423 | -0.0312 | 0.0135 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 381
- **flip_rate**: 0.0474
- **mean_run_length**: 20.05
- **max_run_length**: 72
- **direction_counts**: {'SHORT': 201, 'LONG': 180}
- **directional_entropy**: 0.9978

| Transition | Count |
|------------|------:|
| LONG->LONG | 171 |
| LONG->SHORT | 9 |
| SHORT->LONG | 9 |
| SHORT->SHORT | 191 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0474, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 335 | 54.63 | -0.0009 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |