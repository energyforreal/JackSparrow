# Per-TF transformer bundles

Each subdirectory holds one independently trained transformer for a native timeframe.

## Layout

```
agent/model_storage/
├── JackSparrow_Transformer_BTCUSD_5m/
│   ├── metadata_transformer.json
│   ├── btcusd_5m_transformer.onnx
│   └── feature_config.json
├── JackSparrow_Transformer_BTCUSD_15m/
├── JackSparrow_Transformer_BTCUSD_30m/
├── JackSparrow_Transformer_BTCUSD_1h/
└── JackSparrow_Transformer_BTCUSD_2h/
```

## Training

Train all TFs in Colab via `scripts/colab/transformer_btcusd_all_tf_train_standalone.ipynb`, or via CLI:

```bash
# All TFs (exports to export/JackSparrow_Transformer_BTCUSD_{tf}/)
python scripts/colab/train_transformer_resolution.py --all --export-dir export --continue-on-error

# Single TF
python scripts/colab/train_transformer_resolution.py --resolution 15m --export-dir export/15m
```

Copy exports into the matching subdirectory above.

## Agent config

```env
MODEL_DIR=./agent/model_storage
TRANSFORMER_EXECUTION_TFS=15m,30m
TRANSFORMER_BIAS_TFS=1h,2h
TRANSFORMER_TIMING_TF=5m
TRANSFORMER_MIN_TF_ALIGNMENT=3
```
