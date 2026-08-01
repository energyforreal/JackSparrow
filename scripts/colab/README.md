# Colab notebook helpers (non-production)

Per-TF transformer training for BTCUSD. Each timeframe is trained **independently**;
the agent integrates outputs at decision time via `mtf_decision_policy`.

## Shared modules

- Feature contract: `feature_store/transformer_btcusd/`
- Training loop: `scripts/colab/transformer_training.py`
- CLI runner: `scripts/colab/train_transformer_resolution.py`

## Notebook

`transformer_btcusd_all_tf_train.ipynb` trains all supported resolutions (5m, 15m, 30m, 1h, 2h)
sequentially via `run_all_training()` from `train_transformer_resolution.py`.

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
