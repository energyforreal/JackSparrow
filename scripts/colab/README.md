# Colab notebook helpers (non-production)

Per-TF transformer training for BTCUSD. Each timeframe is trained **independently**;
the agent integrates outputs at decision time via `mtf_decision_policy`.

## Shared modules

- Feature contract: `feature_store/transformer_btcusd/`
- Training loop: `scripts/colab/transformer_training.py`
- CLI runner: `scripts/colab/train_transformer_resolution.py`

## Notebooks (one per TF)

| Notebook | Resolution |
|----------|------------|
| `transformer_btcusd_5m_train.ipynb` | 5m |
| `transformer_btcusd_15m_train.ipynb` | 15m |
| `transformer_btcusd_30m_train.ipynb` | 30m |
| `transformer_btcusd_1h_train.ipynb` | 1h |
| `transformer_btcusd_2h_train.ipynb` | 2h |

Each notebook sets `resolution = "..."` and calls `run_training()` from
`train_transformer_resolution.py`.

## Export

Copy exports into `agent/model_storage/JackSparrow_Transformer_BTCUSD_{tf}/`:
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
