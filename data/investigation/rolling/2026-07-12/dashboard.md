# Rolling Validation Dashboard

Generated: 2026-07-12T06:04:32.432840+00:00
Archive date: 2026-07-12
Baseline commit: `0503847`
Baseline policy: `hold_baseline_policy`

## Weekly metrics

| Window | Candidates | Policy HOLD % | current trades | ml_only EV % | Recommendation |
|--------|------------|---------------|----------------|--------------|----------------|
| 168h | 2107 | 90.5 | 201 | -0.2015 | hold_baseline_policy |
| 720h | 1206 | 77.4 | 273 | -0.2123 | hold_baseline_policy |

## Regime breakdown (168h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | 0.0 | -0.203 | 0.0 |
| ranging | 0.0 | -0.199 | 0.0 |
| unknown | -0.1911 | -0.1917 | 0.0 |

## Regime breakdown (720h)

| Regime | current EV % | ml_only EV % | ml_adopt_flat EV % |
|--------|-------------:|-------------:|-------------------:|
| neutral | -0.2091 | -0.2148 | -0.209 |
| ranging | -0.2264 | -0.2028 | -0.2264 |
| unknown | -0.1931 | -0.1931 | -0.1543 |

## Governance

Policy change requires: rolling replay positive EV, forward shadow G6 pass,
regime-stratified validation, and documented approval against baseline.

See `data/investigation/investigation_closure_2026-07-11.md`.

## Decision Quality Index

Composite DQI: **61.95** (weight coverage 0.55)
