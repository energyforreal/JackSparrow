# Rolling Validation Dashboard

Generated: 2026-07-11T16:34:21.707014+00:00
Archive date: 2026-07-11
Baseline commit: `0503847`
Baseline policy: `hold_baseline_policy`

## Weekly metrics

| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |
|--------|------------|---------------|----------------|--------------|----------------|
| 168h | 2094 | 90.5 | 198 | -0.2015 | hold_baseline_policy |
| 720h | 2363 | 83.8 | 383 | -0.2018 | hold_baseline_policy |

## Regime breakdown (168h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | 0.0 | -0.2027 | 0.0 |
| ranging | 0.0 | -0.2016 | 0.0 |
| unknown | -0.19 | -0.1904 | 0.0 |

## Regime breakdown (720h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | -0.2091 | -0.2025 | -0.209 |
| ranging | -0.2264 | -0.2039 | -0.2264 |
| unknown | -0.1934 | -0.1937 | -0.1543 |

## Governance

Policy change requires: rolling replay positive EV, forward shadow G6 pass,
regime-stratified validation, and documented approval against baseline.

See `data/investigation/investigation_closure_2026-07-11.md`.

## Decision Quality Index

Composite DQI: **61.87** (weight coverage 0.55)
