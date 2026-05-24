# JackSparrow v43 Recovery Runbook

Operational steps for the v43 recovery plan (runtime config → training cost parity → inference A/B → policy re-enable).

Reports are written under `logs/signal_recovery/` (or `LOGS_ROOT/signal_recovery/`).

## P0 — Runtime recovery (no code changes)

Recovery defaults are committed in `.env.example`. Copy secrets into root `.env` if needed; restart agent/backend after changes.

| Variable | Recovery value | Purpose |
|---|---|---|
| `JACKSPARROW_V43_INFERENCE_STACK` | `regressor_mean` | Bypass meta+calibrator until retrain |
| `JACKSPARROW_V43_BLOCK_TRENDING_ENTRIES` | `false` | Allow trending-regime entries |
| `JACKSPARROW_V43_NEAR_THRESHOLD_EPSILON` | `0.0002` | Near-miss raw candidates |
| `JACKSPARROW_V43_MIN_EDGE_COST_RATIO` | `0.5` | Relax Gate 5 edge hurdle |
| `AGENT_POLICY_MODE` | `ml_only` | Remove thesis double-consensus during validation |

Verify loaded config and capture a short soak baseline:

```bash
python scripts/v43_recovery_runbook.py verify-config
python scripts/v43_recovery_runbook.py baseline --hours 6 --tag recovery_p0
python scripts/v43_recovery_runbook.py gate-rejects
python scripts/v43_recovery_runbook.py all-checks --hours 6
```

**P0 success signals:** rising `gates_passed_long` / `gates_passed_short`, fewer `min_edge_cost` and `trending_blocked` rejects, non-zero actionable decisions in telemetry.

## P1 — Training cost parity + retrain

Training uses `compute_v43_round_trip_cost_pct()` in `feature_store/jacksparrow_v43_train_multihead.py` (no leverage in cost). Retrain via Colab notebook or:

```bash
python scripts/train_v43_multihead_export.py --feature-csv <path>
```

After export, promote bundle to `agent/model_storage/JackSparrow_v43_models_BTCUSD/` and run:

```bash
pytest tests/unit/test_jacksparrow_v43_train_multihead.py tests/unit/test_v43_signal_gates.py -q
python scripts/smoke_test_v43.py --base http://127.0.0.1:8000
```

Check metadata `runtime_cost_assumptions.round_trip_cost_pct` ≈ `0.0016` and higher `tradable_label_fraction` per head.

## P2 — Inference stack A/B

```bash
python scripts/v43_recovery_runbook.py ab-plan
```

1. Window A (24h): keep `JACKSPARROW_V43_INFERENCE_STACK=regressor_mean`, capture `baseline --tag regressor_mean`.
2. Window B (24h): set `meta_calibrator`, restart agent, capture `baseline --tag meta_calibrator`.
3. Compare:

```bash
python scripts/v43_recovery_runbook.py ab-compare \
  --baseline logs/signal_recovery/baseline_regressor_mean.json \
  --candidate logs/signal_recovery/baseline_meta_calibrator.json
```

Keep the stack with better actionable rate **and** non-collapsed `expected_return_std`.

## P3 — Re-enable thesis fusion

```bash
python scripts/v43_recovery_runbook.py policy-stage
```

1. Confirm ≥5 trades/day (or acceptable signal frequency) in `ml_only` mode.
2. Set `AGENT_POLICY_MODE=ml_and_thesis` with `AGENT_POLICY_ADOPT_GATED_ML_WHEN_THESIS_NEUTRAL=true`.
3. Monitor for `missing_agent_thesis_confirms_ml` / `fusion_ml_and_thesis_no_agreement` spikes; revert to `ml_only` if throughput collapses.
