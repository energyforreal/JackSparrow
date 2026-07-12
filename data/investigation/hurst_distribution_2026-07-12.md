# Hurst / Feature Distribution — High-Confidence B4

Generated: 2026-07-12T06:04:44.817877+00:00
High-confidence B4: **33** / 33

## Hurst histogram

| Bucket | Count |
|--------|------:|
| 0 | 15 |
| 0-0.3 | 18 |

- Hurst exactly 0: 15 (45.45%)
- ADX < 25: 0 (0.0%)
- Vol regime < 1.1: 33 (100.0%)

## Co-occurrence


hurst_60=0.0 is the clip floor of the variance-ratio estimator in _hurst_fast (RW maps ≈0, not classic Hurst 0.5); fillna(0.5) is warmup-only. See data/investigation/hurst_scale_diagnosis_2026-07-12.md.