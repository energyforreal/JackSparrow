# JackSparrow v43 smoke checklist

Run with **`MODEL_DIR`** set to **`agent/model_storage/JackSparrow_v43_models_BTCUSD`** (or your custom bundle folder—**not** a parent that lacks `metadata_v43.json`). Ensure Delta credentials are set. Optional: **`JACKSPARROW_V43_SHORT_EXECUTION_ENABLED=true`** if you are explicitly testing symmetric shorts (default **OFF**). **`JACKSPARROW_V43_MODE_ENABLED`** is retained for env compatibility (default **true**, marked deprecated in **`agent/core/config.py`** because v43 is the only path). See [`.env.example`](../.env.example).

## Pickle compatibility (mandatory)

The shipped `model_artifact_v43.pkl`, `feature_engineer.pkl`, and `regime_models_v43.pkl` reference `__main__.EnsembleModel`, `__main__.LGBMModel`, and `__main__.FeatureEngineer` — classes that only existed in the Colab training scope. The agent installs minimal stubs via `agent.models.v43_pickle_shims` (auto-imported by `JackSparrowV43Node`) so `joblib.load` succeeds and `EnsembleModel.predict(...)` / `predict_uncertainty(...)` work end-to-end via the stored `_ens_scaler` + `xgb` + `rf` (+ inner `lgbm_model`).

Two known limitations require the **bundle to be re-exported** from the training notebook before full v43 inference is possible:

1. **`feature_engineer.pkl` only stores `self.columns`.** The actual `transform()` body calls `build_feature_matrix(df_5m, df_15m, df_1h, df_funding, for_training=...)` — a notebook-level function that `joblib.dump` does **not** capture. Without it, `fe.transform(...)` raises a clear `RuntimeError`. Fix one of:
   - **Re-export with cloudpickle** (recommended, one line in Colab): `import cloudpickle; cloudpickle.dump({"model": ensemble, "feature_engineer": fe, "features": features, "regime_models": regime_models, "metadata": meta}, open("model_artifact_v43.pkl", "wb"))`. This captures the closure for `FeatureEngineer.transform` and friends.
   - **Or** register the v43 `build_feature_matrix` at agent startup: `from agent.models.v43_pickle_shims import set_v43_build_feature_matrix; set_v43_build_feature_matrix(your_v43_build_feature_matrix)`. The shim's `FeatureEngineer.transform` will delegate to it.
2. **scikit-learn version skew.** The artifact was trained on scikit-learn `1.6.1`; in newer environments the pickled `LGBMRegressor` calls the obsolete `check_array(force_all_finite=...)` kwarg (renamed `ensure_all_finite` in `1.8`). The shim degrades gracefully (skips the failing head, keeps `xgb`+`rf`), but for parity with training, pin `scikit-learn==1.6.*` in `requirements.txt` or retrain with current versions.

## Runtime smoke checklist

1. **Discovery**: Agent logs `model_discovered_v43` and registers exactly one model node. If load fails, the agent logs `model_discovery_v43_failed` and continues without v43 (no startup crash).
2. **delta_client**: `IntelligentAgent` sets `mcp_orchestrator.delta_client`; v43 OHLCV fetch succeeds (no `mcp_orchestrator_v43_no_delta_client`).
3. **Closed bar**: Logs show **`expected_return`**, **`threshold`**, **`regime`**; **`metadata_v43.json`** should carry **`training_forward_bars`** (120) aligned with **`feature_store/jacksparrow_v43_contract.py`**. No errors from **`jack_sparrow_v43_predict_failed`**.
4. **Gates**: When scoring fires, **`mcp_orchestrator_v43_prediction_complete`** includes **`reject=`** if blocked after gate 2+; UI may show **`v43_gate_reject`** on HOLD.
5. **WebSocket / UI**: Signal payload includes **`expected_return`** (preferred) and ancillary **`mcp_tanh_prediction`**; backend may append recent rows to Redis **`jacksparrow:v43:signal_history:<symbol>`** (see [Backend – WebSocket](06-backend.md#websocket-protocol)).
6. **Collapse rate**: Inspect `collapse_rate` in v43 evidence / logs; tune `JACKSPARROW_V43_THRESHOLD_OOF_PERCENTILE` if outside 60–80% over a session.
7. **Adaptive subprocess (v15 parquet path only)**: `ADAPTIVE_RETRAIN_ENABLED=true` with **`ADAPTIVE_LABELED_DATA_SOURCE=parquet`** replays **v15** pipeline bundles — **not** the v43 regression weights. Enable only when you maintain `labeled_5m.parquet` / `labeled_15m.parquet` next to a v15 export; expect tick worker logs (`python -m agent.learning.adaptive.retrain_worker`) and optional `refresh_models` on accept.
8. **Drift consensus**: With `ADAPTIVE_DRIFT_REQUIRE_KS_PSI_CONSENSUS=true`, retrain triggers only when `consensus_drift_count` ≥ `ADAPTIVE_DRIFT_CONSENSUS_MIN_COUNT` (again, **v15** adaptive path).
