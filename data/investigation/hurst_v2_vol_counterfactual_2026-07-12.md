# Hurst v2 + Vol Counterfactual — 2026-07-12

Dual-write rows: **121**

## Distribution

- `hurst_60`: mean=0.027418 median=0.026418 ≥0.52=0
- `hurst_60_v2`: mean=0.515324 median=0.526415 ≥0.52=65

## Trend-continuation fires (offline)

- Legacy flag off: {'long': 0, 'short': 0}
- `AGENT_THESIS_USE_HURST_V2=true` (offline): {'long': 0, 'short': 8}

## Breakout vol_regime counterfactual (offline)

| Vol min | Fires | N | Fire % |
|--------:|------:|--:|-------:|
| 1.1 | 0 | 121 | 0.0 |
| 0.9 | 0 | 121 | 0.0 |
| 0.8 | 0 | 121 | 0.0 |

## Production posture

- Keep `AGENT_THESIS_USE_HURST_V2=false` until replay/EV gates pass
- Do **not** lower `AGENT_THESIS_TREND_HURST_MIN` on legacy scale
- Do **not** promote `neutral_mild_trend`
- Vol 1.1→0.9 remains counterfactual-only pending EV validation

Offline only. Dual-write confirmed in telemetry. Do not enable AGENT_THESIS_USE_HURST_V2 or lower vol floor in production without 7d/30d replay + EV gates.
