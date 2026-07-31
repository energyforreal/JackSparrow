# Colab notebook helpers (non-production)

These files support optional Google Colab workflows for feature engineering and Delta API access.
They are **not** imported by the agent runtime except via shared `feature_store/transformer_btcusd_15m/`.

## BTCUSD 15m Transformer

Train/serve parity modules live in `feature_store/transformer_btcusd_15m/`.
Training loop helpers live in `scripts/colab/transformer_training.py`.

1. Open `scripts/colab/transformer_btcusd_15m_train.ipynb` in Google Colab (or Jupyter locally), run all cells, and set `export_dir` as needed (default `/content/export`).
2. Optional: set `epochs=5` in the config cell for a quick smoke run; set `refresh_data=True` to refetch from Delta API.
3. Copy exports into `agent/model_storage/JackSparrow_Transformer_BTCUSD/`:
   - `btcusd_15m_transformer.onnx`
   - `feature_config.json`
4. Point the agent at the bundle:
   ```env
   MODEL_DIR=./agent/model_storage/JackSparrow_Transformer_BTCUSD
   IC_MODE=false
   ```

For local development, use the main packages under `agent/` and `feature_store/`.
