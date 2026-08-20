# Colab notebook helpers (non-production)

Per-TF transformer training for BTCUSD. Each timeframe is trained **independently**;
the agent integrates outputs at decision time via climate/setup/timing synthesis
(`agent/core/market_understanding.py`).

## Shared modules (repo source of truth)

Transformer train/serve parity lives in **`feature_store/transformer_btcusd/`** (not
`unified_feature_engine.py`, which is for the canonical v5 feature registry).

- Feature contract: `feature_store/transformer_btcusd/`
- Training loop: `scripts/colab/transformer_training.py`
- CLI runner: `scripts/colab/train_transformer_resolution.py`

Before copying a bundle into `agent/model_storage/`, validate it:

```bash
python scripts/validate_transformer_bundle.py agent/model_storage/JackSparrow_Transformer_BTCUSD_15m
```

Parity tests: `pytest tests/unit/test_transformer_btcusd_feature_parity.py`

## Research Colab (v8 multi-horizon 5m)

Primary research trainer: **`transformer_btcusd_next_candle_research.ipynb`**.
It trains a 5m Transformer on wall-clock path behavior at 5m/10m/15m/30m/1h/2h.
Candle/chart geometry is the input; named patterns are secondary. Do not hand-edit
the `.ipynb`.

```bash
python scripts/colab/build_next_candle_research_notebook.py
python scripts/colab/smoke_test_next_candle_notebook.py
```

Sources: `scripts/colab/next_candle_research.py`, `scripts/colab/next_candle_model.py`.
The production all-TF v6 notebook above stays until a v7 export is validated.

**Retrain after horizon/loss changes:** set `refresh_data = True` in the Colab config cell so
cached parquet is rebuilt with new label horizons (or delete `/content/cache/*.parquet`).

Per-TF defaults: path labels (no `future_return` head) plus v6 pattern heads
(`future_structure_outcome`, next-bar `future_candle_class`) and
`candle_follow_through_atr` / `structure_delta`. Export sanity gate uses
`future_volatility` test correlation. `continuous_loss_weights` zeros out
`future_volume_change_pct` loss (it dominated the shared encoder). Agent uses
`path_edge = mfe - mae` for directional signals; pattern heads only modulate
setup/timing.

## Notebook

Upload **`transformer_btcusd_all_tf_train_standalone.ipynb`** to Google Colab (single file,
no GitHub clone, no data uploads). All training code is **inline** in readable Python cells.
The only external input at runtime is the **Delta Exchange India public API**.
Run all cells top-to-bottom: config → train → summary → diagnostics → download.

### Troubleshooting map

| Notebook section | Repo source | What to inspect |
|------------------|-------------|-----------------|
| Feature contract | `contract.py` | `FEATURE_COLS`, `feature_cols_for_resolution`, horizons |
| Derivatives | `derivatives.py` | Funding/OI z-scores |
| Market structure | `structure.py` | ZigZag HH/HL, S/R, compression, breakout, geometry |
| Feature engineering | `features.py` | `add_features` |
| Labels / targets | `labels.py` | `compute_market_labels` |
| Inference helpers | `inference.py` | `feature_config.json` builders |
| Delta data | `transformer_data.py` | `fetch_candles`, `fetch_history_bundle` |
| Training pipeline | `transformer_training.py` | Model, loss, ONNX export |
| Training runner | `train_transformer_resolution.py` | `run_all_training` |

Edits made directly in Colab are ephemeral. For permanent changes, edit the repo `.py` files
and regenerate the notebook.

Regenerate after changing training source:

```bash
python scripts/colab/build_standalone_notebook.py
python scripts/colab/smoke_test_notebook_structure.py
```

Set `resolutions` in the config cell to train a subset, e.g. `["15m", "1h"]`.

## CLI

Single TF:

```bash
python scripts/colab/train_transformer_resolution.py --resolution 15m --export-dir export/15m
```

All TFs:

```bash
python scripts/colab/train_transformer_resolution.py --all --export-dir export --continue-on-error
```

## Export

Each TF exports to `export/JackSparrow_Transformer_BTCUSD_{tf}/`. Copy into
`agent/model_storage/JackSparrow_Transformer_BTCUSD_{tf}/`:
- `metadata_transformer.json` (auto-generated)
- `btcusd_{tf}_transformer.onnx`
- `feature_config.json`

## Agent config

```env
MODEL_DIR=./agent/model_storage
TRANSFORMER_EXECUTION_TFS=15m,30m
TRANSFORMER_BIAS_TFS=1h,2h
TRANSFORMER_TIMING_TF=5m
TRANSFORMER_MIN_TF_ALIGNMENT=3
```
