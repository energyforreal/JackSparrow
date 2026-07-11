# Calibration Status — 2026-07-11

## Result

`build_calibration_dataset.py` produced **0 calibration rows**.

**Cause:** Calibration dataset requires executed trade outcomes with confidence labels. Current window has `executed_rate: 0.0` in attribution funnel (168h telemetry, 2803 samples).

## Attribution context (168h)

| Metric | Value |
|--------|------:|
| Policy HOLD | 2608 / 2803 (93%) |
| Handler `hold_at_synthesis` | 306 |
| ML gated pass rate (G1–G5) | 74.4% |
| Executions | 0 |

## Next steps

1. Re-run after any live executions accumulate:
   ```powershell
   python tools/commands/build_calibration_dataset.py
   python tools/commands/fit_calibrator.py
   ```
2. Interim: use forward-return labels from rolling replay for ablation (done — [`ablation_report_2026-07-11.md`](ablation_report_2026-07-11.md))
3. Target: reliability curves once ≥30 labeled execution rows exist

## Brier / ECE

Not computed — insufficient executed-trade labels. Document ECE/Brier when `calibration_dataset.json` has rows.
