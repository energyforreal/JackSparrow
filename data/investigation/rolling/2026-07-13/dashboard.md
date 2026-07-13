# Rolling Validation Dashboard

Generated: 2026-07-13T06:06:10.725683+00:00
Archive date: 2026-07-13
Baseline commit: `0503847`
Baseline policy: `hold_baseline_policy`

## Weekly metrics

| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |
|--------|------------|---------------|----------------|--------------|----------------|
| 168h | 2348 | 91.8 | 193 | -0.2043 | hold_baseline_policy |
| 720h | 3040 | 86.7 | 403 | -0.2038 | hold_baseline_policy |

## Regime breakdown (168h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | 0.0 | -0.2043 | 0.0 |
| ranging | 0.0 | -0.2043 | 0.0 |
| unknown | -0.191 | -0.2046 | 0.0 |

## Regime breakdown (720h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | -0.2091 | -0.2038 | -0.209 |
| ranging | -0.2264 | -0.2038 | -0.2264 |
| unknown | -0.1923 | -0.2039 | -0.1543 |

## Governance

Policy change requires: rolling replay positive EV, forward shadow G6 pass,
regime-stratified validation, and documented approval against baseline.

See `data/investigation/investigation_closure_2026-07-11.md`.

## Decision Quality Index

Composite DQI: **62.26** (weight coverage 0.55)
