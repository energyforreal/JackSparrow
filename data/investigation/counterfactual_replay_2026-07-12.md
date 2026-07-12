# Counterfactual Replay Report

Generated: 2026-07-12T02:31:45.393581+00:00
Window hours: 168.0
Candidates labeled: 2113

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 201 | 11.44 | 0.041 | -0.1911 | 1.9203 | 10.05 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2113 | 3.08 | 0.015 | -0.2026 | 21.3994 | 105.65 | 2.0 |
| no_adx | 220 | 10.45 | 0.037 | -0.1917 | 2.109 | 11.0 | 2.0 |
| no_thesis_veto | 2113 | 3.08 | 0.015 | -0.2026 | 21.3994 | 105.65 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 2113
- **flip_rate**: 0.0563
- **mean_run_length**: 17.61
- **max_run_length**: 118
- **direction_counts**: {'SHORT': 987, 'LONG': 1126}
- **directional_entropy**: 0.9969

| Transition | Count |
|------------|------:|
| LONG->LONG | 1066 |
| LONG->SHORT | 59 |
| SHORT->LONG | 60 |
| SHORT->SHORT | 927 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0563, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1893 | 2.22 | -0.2038 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |