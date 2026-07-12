# Counterfactual Replay Report

Generated: 2026-07-12T06:02:18.052119+00:00
Window hours: 168.0
Candidates labeled: 2107

## Scenario table

| Scenario | Trades | Win % | PF | EV % | Max DD % | Exposure | Avg hold |
|----------|--------|-------|-----|------|----------|----------|----------|
| current | 201 | 11.44 | 0.041 | -0.1911 | 1.9203 | 10.05 | 2.0 |
| ml_adopt_flat | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_adopt_flat_score50 | 0 | None | None | 0.0 | 0.0 | 0.0 | None |
| ml_only | 2107 | 3.13 | 0.019 | -0.2015 | 21.3074 | 105.35 | 2.0 |
| no_adx | 220 | 10.45 | 0.037 | -0.1917 | 2.109 | 11.0 | 2.0 |
| no_thesis_veto | 2107 | 3.13 | 0.019 | -0.2015 | 21.3074 | 105.35 | 2.0 |
| neutral_mild_trend | 5 | 0.0 | 0.0 | -0.2311 | 0.0578 | 0.25 | 2.0 |

## Directional stability

- **sample_count**: 2107
- **flip_rate**: 0.0575
- **mean_run_length**: 17.27
- **max_run_length**: 118
- **direction_counts**: {'SHORT': 995, 'LONG': 1112}
- **directional_entropy**: 0.9978

| Transition | Count |
|------------|------:|
| LONG->LONG | 1051 |
| LONG->SHORT | 60 |
| SHORT->LONG | 61 |
| SHORT->SHORT | 934 |

## Promotion gates

**Recommendation:** hold_baseline_policy
- G1_sample_size: FAIL (value=0, threshold=30)
- G2_net_ev: FAIL (value=0.0, threshold=> 0)
- G3_max_dd: PASS (value=0.0, threshold=<= 5.0%)
- G4_regime: FAIL (value=False, threshold=positive EV in non-ranging bucket)
- G5_stability: PASS (value=0.0575, threshold=<= 0.5)

## Threshold sensitivity

| Min score | Trades | Win % | EV % |
|-----------|--------|-------|------|
| 45 | 1887 | 2.28 | -0.2027 |
| 50 | 0 | None | 0.0 |
| 55 | 0 | None | 0.0 |
| 60 | 0 | None | 0.0 |