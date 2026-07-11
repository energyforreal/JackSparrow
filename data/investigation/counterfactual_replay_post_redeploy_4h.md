# Counterfactual Replay Report

Generated: 2026-07-11T12:31:53.843162+00:00
Window hours: 4.0
Candidates labeled: 49

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 49 | 2.04 | 0.16 | -0.1607 | 0.4688 | 2.45 | 1.98 |
| no_adx | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| no_thesis_veto | 49 | 2.04 | 0.16 | -0.1607 | 0.4688 | 2.45 | 1.98 |

## Directional stability

- **sample_count**: 49
- **flip_rate**: 0.1042
- **mean_run_length**: 8.17
- **max_run_length**: 18
- **direction_counts**: {'LONG': 26, 'SHORT': 23}
- **directional_entropy**: 0.9973

| Transition | Count |
|------------|------:|
| LONG->LONG | 23 |
| LONG->SHORT | 3 |
| SHORT->LONG | 2 |
| SHORT->SHORT | 20 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.1042, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 49 | 2.04 | -0.1607 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |