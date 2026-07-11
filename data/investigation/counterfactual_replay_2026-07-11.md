# Counterfactual Replay Report

Generated: 2026-07-11T07:51:36.151806+00:00
Window hours: 12.0
Candidates labeled: 182

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 182 | 1.65 | 0.046 | -0.1826 | 1.7369 | 9.1 | 1.99 |
| no_adx | 4 | 0.0 | 0.0 | -0.2095 | 0.0419 | 0.2 | 2.0 |
| no_thesis_veto | 182 | 1.65 | 0.046 | -0.1826 | 1.7369 | 9.1 | 1.99 |

## Directional stability

- **sample_count**: 182
- **flip_rate**: 0.0939
- **mean_run_length**: 10.11
- **max_run_length**: 33
- **direction_counts**: {'LONG': 94, 'SHORT': 88}
- **directional_entropy**: 0.9992

| Transition | Count |
|------------|------:|
| LONG->LONG | 85 |
| LONG->SHORT | 9 |
| SHORT->LONG | 8 |
| SHORT->SHORT | 79 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0939, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 178 | 1.69 | -0.182 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |