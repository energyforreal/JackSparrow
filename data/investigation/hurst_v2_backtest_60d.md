# Hurst v2 Historical Backtest

Generated: 2026-07-12T12:50:15.419332+00:00
Candles: 18144 | eval bars: 17732 | horizon: 12 bars | window: None

Directional read only — no slippage/funding/walk-forward. Does not clear promotion gate alone.

## Hurst distribution (eval bars)

- `hurst_60`: n=17732 mean=0.017944 median=0.0 ≥0.52=18 eq0=12411
- `hurst_60_v2`: n=17732 mean=0.420639 median=0.44144 ≥0.52=4175 eq0=689

## Arm comparison

| Arm | n_fires | n_long | n_short | fire% | EV long% | EV short% | EV combined% |
|-----|--------:|-------:|--------:|------:|---------:|----------:|-------------:|
| legacy | 1615 | 727 | 888 | 9.108 | 0.1535 | -0.015 | 0.0608 |
| hurst_v2 | 2548 | 1074 | 1474 | 14.37 | 0.0853 | -0.0183 | 0.0254 |

## Regime fire counts (hurst_v2)

- `crisis`: 381
- `neutral`: 2129
- `ranging`: 38

## Production posture

- Do **not** enable `AGENT_THESIS_USE_HURST_V2` on live capital from this report alone.
- Requires 7d+30d replay + shadow + approval vs baseline `0503847`.
