# Training and Feature Parity

## Purpose

This guide reconciles the current notebook workflow with live agent requirements so training outputs can be deployed without schema drift.

## Authoritative Training Path

Use:

- `notebooks/JackSparrow_Trading_Colab_v4.ipynb`

This notebook is the production-style path for BTCUSD entry/exit ensembles. It uses:

- `UnifiedFeatureEngine`
- `EXPANDED_FEATURE_LIST` from `feature_store/feature_registry.py` (canonical + patterns + **MTF context**; count bumps with `FEATURE_VERSION`, currently ~127)
- Fee-aware TP/SL outcome labeling
- Metadata + artefact export per timeframe

Legacy notebooks such as `notebooks/train_models_colab.ipynb` and `notebooks/train_xgboost_colab.ipynb` can be used for experiments, but they are not the default deployment authority.

## Quick Verdict Table

| Claim | Legacy notebooks | `JackSparrow_Trading_Colab_v4.ipynb` |
| --- | --- | --- |
| Pattern features included | Often no | Yes (`cdl_*`, `sr_*`, `tl_*`, `chp_*`, `bo_*`) |
| Fee-aware TP/SL labels | Often no | Yes |
| Scalping-ready defaults | Depends | Default fetch: `1m`–`15m` with per-TF candle targets; MTF columns are informative on **5m** primary bars |
| Train-serve alignment safety | Manual | Explicit metadata parity checks in notebook |

## Post-Train Checklist

1. Export and keep all artefacts together (`entry_*`, `exit_*`, scalers, `features_*.json`, `metadata_*.json`).
2. Set `MODEL_DIR` to the exact directory containing `metadata_BTCUSD_*.json`.
3. Verify metadata `features` and `features_required` match `EXPANDED_FEATURE_LIST` order and length.
4. Run:
   - `pytest tests/unit/test_feature_parity.py -q`
5. Run model loading smoke test against the promoted folder:
   - `python scripts/test_model_inference.py --model-dir agent/model_storage/jacksparrow_v5_BTCUSD_YYYY-MM-DD`
6. Spot-check notebook outputs for feature-importance concentration and class balance.

## Why HOLD Can Still Dominate

Even with expanded features and better labels, HOLD can remain dominant because runtime decisioning applies:

- Consensus neutral bands in reasoning
- Model-disagreement damping
- Confidence and market-condition execution gates

See `docs/analysis/HOLD_SIGNAL_DIAGNOSIS.md` for code-traced details.

## Scalping profile alignment

If your target is scalping (quick entry and exit), tune runtime settings to the same horizon used in training:

- Reasoning confidence bands and decision gating (`min_confidence_threshold`)
- Risk profile (`STOP_LOSS_PERCENTAGE`, `TAKE_PROFIT_PERCENTAGE`)
- Monitoring cadence (`position_monitor_interval_seconds`, `min_monitor_interval_seconds`)

Do not assume 5m/15m model training alone makes runtime behavior scalping-ready; align the agent profile and validate on paper trading metrics.
