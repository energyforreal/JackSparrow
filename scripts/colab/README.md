# Colab notebook helpers (non-production)

## Fused multi-TF trainer (live path)

```bash
python scripts/colab/train_mtf_fusion.py --export-dir export/mtf_fusion
```

Sources: `scripts/colab/mtf_fusion_model.py`, `scripts/colab/mtf_fusion_research.py`.
10m OHLCV is built from two closed 5m bars outside the model. Walk-forward never sees the final test split.

## Per-TF transformer training (rollback only)

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

## Research Colab (v10 fused multi-TF)

Primary research trainer: **`transformer_btcusd_next_candle_research.ipynb`**.
It trains the live fused model: independent 5m/10m/30m/1h/2h OHLCV, shared encoder,
softmax TF weights, and four 3-class heads (+10m/+30m/+1h/+2h). 10m is two closed
5m bars built outside the encoder. Walk-forward, Optuna, and temperature fitting
never see the final test split. Do not hand-edit the `.ipynb`.

Training-logic changes belong in the `.py` sources. Regenerate the notebook after
every fusion training or contract change:

```bash
python scripts/colab/build_next_candle_research_notebook.py
python scripts/colab/smoke_test_next_candle_notebook.py
```

Sources: `scripts/colab/mtf_fusion_model.py`, `scripts/colab/mtf_fusion_research.py`,
`feature_store/transformer_btcusd/mtf_*.py`. Local CLI equivalent:
`python scripts/colab/train_mtf_fusion.py --export-dir export/mtf_fusion`.

**Retrain after horizon/label changes:** set `refresh_data = True` in the Colab load
cell so cached parquet is rebuilt (or delete `/content/cache/*.parquet`).

## Colab CLI via WSL (Windows)

The [Google Colab CLI](https://github.com/googlecolab/google-colab-cli) is
Linux/macOS only. On this Windows machine it runs inside Ubuntu WSL.

One-time setup (installs Ubuntu-24.04 if needed, then `google-colab-cli`):

```powershell
powershell -File scripts/colab/setup_wsl_colab_cli.ps1
wsl -d Ubuntu-24.04 -- bash -lc "colab sessions"
```

The first `colab` command prints a Google URL. Sign in, paste the code back
into the WSL prompt, then run the fused research notebook on a T4:

## Rotate among 3 Google accounts (GPU quota)

Colab GPU usage limits are per Google account. This repo does **not** log into
Google for you. A local helper tracks which of your three emails is cooling
down and tells you which account to sign into next.

```powershell
python scripts/colab/rotate_colab_accounts.py init
# edit scripts/colab/colab_accounts.json with your three emails
python scripts/colab/rotate_colab_accounts.py use you+colab1@gmail.com
python scripts/colab/rotate_colab_accounts.py status
```

When a GPU quota message appears (or after `run_colab_cli` fails that way):

```powershell
python scripts/colab/rotate_colab_accounts.py mark-quota
```

Then sign into the printed Gmail in the browser, run
`wsl -d Ubuntu-24.04 -- bash -lc "colab sessions"`, and paste the new OAuth
code. High demand / 503 capacity is **not** quota — stay on the same account
and retry. Cooldown defaults to 24 hours (`cooldown_hours` in the JSON).

```powershell
powershell -File scripts/colab/run_colab_cli.ps1
```

Useful flags (forwarded into WSL): `--gpu A100`, `--keep`, `--stop-existing`,
`--timeout 28800`. `colab exec` defaults to 30s; the wrapper raises that so
training can finish. The runner downloads
`export/JackSparrow_Transformer_BTCUSD_mtf_fusion.zip` and stops the VM unless
`--keep` is set. Do not change the WSL default distro; Docker Desktop stays
default and the scripts always pass `-d Ubuntu-24.04`.

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
