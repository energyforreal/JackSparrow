# Metric Ablation Report

Generated: 2026-07-11T12:32:30.784411+00:00

## Statistical LOO Ablation

- Baseline AUC: 0.2645
- Baseline Brier: 0.012739

| Removed | ΔAUC | ΔBrier | max|corr| | Recommendation |
|---------|------|--------|----------|----------------|
| epsilon_proxy | 0.0 | 0.0 | 0.2242 | keep |
| kappa_raw | 0.0 | 0.0 | 1.0 | remove |
| q | 0.0 | 0.0 | 1.0 | remove |
| A | 0.0 | 0.0 | 0.9622 | remove |
| trade_score | -0.190323 | -0.00028 | 1.0 | keep |
| conviction | 0.0 | 0.0 | 1.0 | remove |
| hypothesis_margin | 0.0 | 0.0 | 0.9622 | remove |

## Policy Module Impact (telemetry)

- **conviction_floor**: blocked 0 (0.0%) — Observed terminal_cause=conviction in telemetry
- **entry_quality_veto**: blocked 0 (0.0%) — Observed terminal_cause=quality in telemetry
- **gate5**: blocked 0 (0.0%) — Observed terminal_cause=g5 in telemetry
- **trade_score_hard_veto**: blocked 0 (0.0%) — Observed terminal_cause=policy in telemetry

## Gate

Do not proceed to Phase 7 latent policy refactor until this report is reviewed.