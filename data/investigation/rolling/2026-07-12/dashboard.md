# Rolling Validation Dashboard

Generated: 2026-07-12T10:33:49.082028+00:00
Archive date: 2026-07-12
Baseline commit: `0503847`
Baseline policy: `hold_baseline_policy`

## Weekly metrics

| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |
|--------|------------|---------------|----------------|--------------|----------------|
| 168h | 2102 | 90.9 | 192 | -0.202 | hold_baseline_policy |
| 720h | 2657 | 85.1 | 395 | -0.2022 | hold_baseline_policy |

## Regime breakdown (168h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | 0.0 | -0.2034 | 0.0 |
| ranging | 0.0 | -0.2013 | 0.0 |
| unknown | -0.1906 | -0.1914 | 0.0 |

## Regime breakdown (720h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | -0.2091 | -0.2036 | -0.209 |
| ranging | -0.2264 | -0.2023 | -0.2264 |
| unknown | -0.1928 | -0.1899 | -0.1543 |

## Governance

Policy change requires: rolling replay positive EV, forward shadow G6 pass,
regime-stratified validation, and documented approval against baseline.

See `data/investigation/investigation_closure_2026-07-11.md`.

## Decision Quality Index

Composite DQI: **62.11** (weight coverage 0.55)
