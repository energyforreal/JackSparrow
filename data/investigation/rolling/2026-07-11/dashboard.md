# Rolling Validation Dashboard

Generated: 2026-07-11T12:31:04.000810+00:00
Archive date: 2026-07-11
Baseline commit: `0503847`
Baseline policy: `hold_baseline_policy`

## Weekly metrics

| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |
|--------|------------|---------------|----------------|--------------|----------------|
| 168h | 2084 | 90.8 | 191 | -0.201 | hold_baseline_policy |
| 720h | 2299 | 83.7 | 374 | -0.2027 | hold_baseline_policy |

## Regime breakdown (168h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | 0.0 | -0.2024 | 0.0 |
| ranging | 0.0 | -0.2016 | 0.0 |
| unknown | -0.1873 | -0.1877 | 0.0 |

## Regime breakdown (720h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | -0.2091 | -0.2038 | -0.209 |
| ranging | -0.2264 | -0.2039 | -0.2264 |
| unknown | -0.1913 | -0.1917 | -0.1543 |

## Governance

Policy change requires: rolling replay positive EV, forward shadow G6 pass,
regime-stratified validation, and documented approval against baseline.

See `data/investigation/investigation_closure_2026-07-11.md`.