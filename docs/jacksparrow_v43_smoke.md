# JackSparrow v43 smoke checklist

Run with **`MODEL_DIR`** set to **`agent/model_storage/JackSparrow_v43_models_BTCUSD`** (or your custom bundle folder—**not** a parent that lacks `metadata_v43.json`). Ensure Delta credentials are set. Optional: **`JACKSPARROW_V43_SHORT_EXECUTION_ENABLED=true`** if you are explicitly testing symmetric shorts (default **OFF**). **`JACKSPARROW_V43_MODE_ENABLED`** is retained for env compatibility (default **true**, marked deprecated in **`agent/core/config.py`** because v43 is the only path). See [`.env.example`](../.env.example).

After Colab’s **`jacksparrow_v43_bundle.zip`** unpack (e.g. `%USERPROFILE%\Downloads\jacksparrow_v43_bundle(1)\`):

1. Back up existing `metadata_v43.json`, `model_artifact_v43.pkl`, and `model_artifact_v43_patched.pkl` in **`MODEL_DIR`**.
2. Copy the new **`metadata_v43.json`** and **`model_artifact_v43.pkl`** into **`agent/model_storage/JackSparrow_v43_models_BTCUSD/`** (or your **`MODEL_DIR`**).
3. From repo root: `python scripts/patch_v43_model_artifact.py` — writes **`model_artifact_v43_patched.pkl`** (what the agent loads by default).
4. Restart the agent.

Full steps: [ML models — Operational Workflow](03-ml-models.md#operational-workflow-bundle-first) and [v43 runbook — Promoting a Colab export](v43_trade_execution_runbook.md#promoting-a-colab-export-into-the-repo).

## Pickle compatibility (mandatory)

The shipped `model_artifact_v43.pkl` / `model_artifact_v43_patched.pkl` reference `__main__.EnsembleModel`, `__main__.LGBMModel`, and `__main__.FeatureEngineer` — classes that only existed in the Colab training scope. The agent installs stubs via `agent.models.v43_pickle_shims` (auto-imported by `JackSparrowV43Node`) so `joblib.load` succeeds. Pattern 3 bundles add `ensemble.meta` (LGBMClassifier) + `ensemble.calibrator` (Ridge); `predict()` maps meta proba → calibrator (2D input) → clipped expected return.

The hardened training notebook exports the `FeatureEngineer` as a column contract and relies on the runtime-registered `build_v43_feature_matrix` path. If you are validating an older artifact, check these historical limitations:

1. **`feature_engineer.pkl` only stores `self.columns`.** This is expected for hardened exports. `JackSparrowV43Node` registers the repository v43 feature matrix at import time, and the shim's `FeatureEngineer.transform` delegates to it. If an older artifact still pickles notebook-local closures, prefer re-exporting with the current notebook rather than relying on those closures.
2. **scikit-learn version skew.** The artifact was trained on scikit-learn `1.6.1`; in newer environments the pickled `LGBMRegressor` calls the obsolete `check_array(force_all_finite=...)` kwarg (renamed `ensure_all_finite` in `1.8`). The shim degrades gracefully (skips the failing head, keeps `xgb`+`rf`), but for parity with training, pin `scikit-learn==1.6.*` in `requirements.txt` or retrain with current versions.
3. **v43 predict context frames.** `JackSparrowV43Node` requires **`v43_df5m`** and **`v43_df_funding`** as non-empty `pandas.DataFrame` objects. **`v43_df15m`** and **`v43_df1h`** may be omitted or set to `None`; the node substitutes empty frames because `build_v43_feature_matrix` derives HTF columns from the 5m grid only. **`v43_df_oi`** (expanded ticker ring buffer: OI + bid/ask + bands) and **`v43_df_mark`** (`MARK:BTCUSD` 5m) come from `fetch_v43_market_frames`; sparse/missing columns zero-fill until history accumulates.

4. **Public ticker + products (read-only).** Ticker/OI and contract state use **`JACKSPARROW_V43_OI_PUBLIC_BASE_URL`** (default `https://api.india.delta.exchange`), separate from testnet trading REST. Disable ticker fetch with **`JACKSPARROW_V43_OI_ENABLED=false`**. Contract health gates use **`GET /v2/products/{symbol}`** (cached ~60s).

5. **Feature contract v4.** New exports use 52 features (`jacksparrow_v43_features_v4`: adds `funding_rate_roc`). Legacy v3 (51), v2 (44), and v1 (40) bundles still load. Retrain with `MARK:BTCUSD` candles + real ticker/OI CSV before promoting a v4 bundle.

## Runtime smoke checklist

1. **Discovery**: Agent logs `model_discovered_v43` and registers exactly one model node. If load fails, the agent logs `model_discovery_v43_failed` and continues without v43 (no startup crash).
2. **delta_client**: `IntelligentAgent` sets `mcp_orchestrator.delta_client`; v43 OHLCV fetch succeeds (no `mcp_orchestrator_v43_no_delta_client`).
3. **Closed bar**: Logs show **`expected_return`**, **`threshold`**, **`regime`**; **`metadata_v43.json`** should carry **`training_forward_bars`** (120) aligned with **`feature_store/jacksparrow_v43_contract.py`**. No errors from **`jack_sparrow_v43_predict_failed`**.
4. **Gates**: When scoring fires, **`mcp_orchestrator_v43_prediction_complete`** includes **`reject=`** if blocked after gate 2+; UI may show **`v43_gate_reject`** on HOLD.
5. **WebSocket / UI**: Signal payload includes **`expected_return`** (preferred) and ancillary **`mcp_tanh_prediction`**; backend may append recent rows to Redis **`jacksparrow:v43:signal_history:<symbol>`** (see [Backend – WebSocket](06-backend.md#websocket-protocol)).
6. **Collapse rate**: Inspect `collapse_rate` in v43 evidence / logs; tune `JACKSPARROW_V43_THRESHOLD_OOF_PERCENTILE` if outside 60–80% over a session.
7. **Adaptive subprocess (v15 parquet path only)**: `ADAPTIVE_RETRAIN_ENABLED=true` with **`ADAPTIVE_LABELED_DATA_SOURCE=parquet`** replays **v15** pipeline bundles — **not** the v43 regression weights. Enable only when you maintain `labeled_5m.parquet` / `labeled_15m.parquet` next to a v15 export; expect tick worker logs (`python -m agent.learning.adaptive.retrain_worker`) and optional `refresh_models` on accept.
8. **Drift consensus**: With `ADAPTIVE_DRIFT_REQUIRE_KS_PSI_CONSENSUS=true`, retrain triggers only when `consensus_drift_count` ≥ `ADAPTIVE_DRIFT_CONSENSUS_MIN_COUNT` (again, **v15** adaptive path).
