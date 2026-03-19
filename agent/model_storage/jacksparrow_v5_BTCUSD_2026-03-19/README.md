JackSparrow v5 BTCUSD Models (Expanded Features)
================================================

This directory is the **target for v5 trained models** (expanded ~122 feature schema).

After training in Colab and downloading the ZIP:

1. Extract the ZIP contents into this folder. The ZIP contains:
   - `entry_model_BTCUSD_<tf>.joblib`
   - `entry_scaler_BTCUSD_<tf>.joblib`
   - `exit_model_BTCUSD_<tf>.joblib`
   - `exit_scaler_BTCUSD_<tf>.joblib`
   - `features_BTCUSD_<tf>.json`
   - `metadata_BTCUSD_<tf>.json`

2. Set `MODEL_DIR` to this folder:
   - `MODEL_DIR=./agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19`
   - (See `agent/.env.example`)

3. Restart the agent so discovery loads the new models.

v5 uses the expanded feature set (canonical 50 + candlestick + chart patterns).
Ensure the feature server provides all 122 features when models request them.

Rollback: To revert to v4, set `MODEL_DIR=./agent/model_storage/jacksparrow_v4_BTCUSD`.
