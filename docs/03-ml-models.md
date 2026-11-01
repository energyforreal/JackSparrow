# ML Model Management Documentation

## Overview

JackSparrow’s live path is **`forecast_30m`**: the v5 XGBoost direction head in `JackSparrow_Forecast_BTCUSD_30m/`. That bundle was force-promoted after the development expectancy gate failed; `probability_floor` is 0.55. Closed 30-minute bars map BEARISH/BULLISH to SELL/BUY when probability clears the floor. One position is reserved for 12 hours. SL/TP is ATR-scaled. See [`reference/forecast-30m-h24-spec.md`](../reference/forecast-30m-h24-spec.md).

Rollback: `TRANSFORMER_DECISION_PATH=mtf_fusion` reloads the fused multi-TF Transformer (`JackSparrow_Transformer_BTCUSD_mtf_fusion`). Emergency `transformer_agent_synthesis` reloads the five per-TF ONNX bundles. Those paths are not dual-running.

The fused v11 model encodes independent OHLCV for 5m / 10m / 30m / 1h / 2h, then three 2-class heads forecast **+30m / +1h / +2h** as BULL / BEAR. [`agent/core/fusion_policy.py`](../agent/core/fusion_policy.py) applies frozen walk-forward grades. **Label V2** path targets train the research v15 bundle only; see [`reference/label-v2-spec.md`](../reference/label-v2-spec.md). They are not consumed by live fusion or by the v5 forecast.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Runtime discovery (Transformer ONNX)](#runtime-discovery-transformer-onnx)
- [Runtime discovery (30-minute forecast)](#runtime-discovery-30-minute-forecast)
- [Bundle layout](#bundle-layout)
- [Feature contract](#feature-contract)
- [Environment variables](#environment-variables)
- [Training and export](#training-and-export)
- [Model discovery and registration](#model-discovery-and-registration)
- [Docker](#docker)
- [Troubleshooting](#troubleshooting)
- [Archived inference families](#archived-inference-families)
- [Research: 15-minute recognition](#research-15-minute-recognition)
- [Related documentation](#related-documentation)

---

## Runtime discovery (Transformer ONNX)

Point **`MODEL_DIR`** at **`agent/model_storage/`** (parent directory). The live fused bundle is:

`JackSparrow_Transformer_BTCUSD_mtf_fusion/`

Required artifacts:

| File | Purpose |
|------|---------|
| `metadata_transformer.json` | Bundle manifest (gates, fusion weights, ONNX filename) |
| `btcusd_mtf_fusion.onnx` | ONNX model (loaded via `onnxruntime`) |
| `feature_config.json` | Feature names, window length, horizon gates |

`ModelDiscovery.discover_models()` in [`agent/models/model_discovery.py`](../agent/models/model_discovery.py):

1. Scans `MODEL_DIR` for `JackSparrow_Transformer_BTCUSD_*`
2. If `TRANSFORMER_DECISION_PATH=mtf_fusion` (default) and the fused bundle exists, registers **only** `FusionModelNode`
3. Per-TF bundles remain on disk for emergency rollback and are ignored while the fused bundle is present

`ModelDiscovery.discover_models()` in [`agent/models/model_discovery.py`](../agent/models/model_discovery.py):

1. Scans `MODEL_DIR` for subdirs matching `JackSparrow_Transformer_BTCUSD_*`
2. Verifies ONNX and `feature_config.json` exist per bundle
3. Instantiates `TransformerModelNode.from_metadata_path()` for each
4. Registers all nodes when `MODEL_AUTO_REGISTER=true`
5. Logs **`model_discovered_transformer`** on success

**`MODEL_PATH` is ignored** — use `MODEL_DIR` only.

---

## Runtime discovery (30-minute forecast)

When `TRANSFORMER_DECISION_PATH=forecast_30m` (Docker default), discovery registers **only** `ForecastModelNode` from:

`JackSparrow_Forecast_BTCUSD_30m/`

Required artifacts: `manifest.json` (`orders_enabled` must be true) and `models.joblib`. Unapproved research artifacts are refused.

---

## Bundle layout

```
agent/model_storage/
├── JackSparrow_Transformer_BTCUSD_mtf_fusion/
│   ├── metadata_transformer.json
│   ├── btcusd_mtf_fusion.onnx
│   └── feature_config.json
└── JackSparrow_Forecast_BTCUSD_30m/   # present only after a passing v5 gate
    ├── manifest.json
    └── models.joblib
```

Older per-TF folders (`JackSparrow_Transformer_BTCUSD_{5m,15m,30m,1h,2h}/`) may remain unused.

Each subdirectory contains `metadata_transformer.json`, `btcusd_{tf}_transformer.onnx`, and `feature_config.json`.

Default in [`agent/core/config.py`](../agent/core/config.py):

```bash
MODEL_DIR=./agent/model_storage
```

---

## Feature contract

Train/serve parity lives in [`feature_store/transformer_btcusd/`](../feature_store/transformer_btcusd/):

- `contract.py` — per-TF v9 plus fused live v11 (`FEATURE_CONTRACT_VERSION_V11`, 2-class BEAR/BULL) and research v15 (`FEATURE_CONTRACT_VERSION_V15`, four Label V2 heads h10m/h15m/h30m/h1h; v14 continuous groups + state embeddings)
- `mtf_frames.py`, `mtf_features.py`, `mtf_labels.py` — independent TFs, native encodings, live ignore_index NEUTRAL
- `mtf_labels_v2.py` — Label V2 path targets. Research trainer uses 3-class direction plus ret / long-short MFE/MAE; persist/TP-SL stay diagnostics. Not loaded by the live fused model
- `features.py`, `derivatives.py` — native TF feature matrix
- `inference.py` — ONNX input assembly + metadata export
- `labels.py` — legacy per-TF training label helpers (Colab)

Each `TransformerModelNode` builds features on its native TF grid only.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIR` | `./agent/model_storage` | Parent directory for model bundles |
| `TRANSFORMER_DECISION_PATH` | `forecast_30m` | Live path (force-promoted v5). Rollback: `mtf_fusion`. Emergency: `transformer_agent_synthesis` |
| `TRANSFORMER_MIN_CONFIDENCE` | `0.55` | Per-horizon probability floor |
| `SL_TP_MODE` | `atr` | Duration-scaled ATR brackets (fusion default) |
| `TRANSFORMER_CONFIDENCE_HOLD_FLOOR` | `0.40` | Soft confidence floor used in size bands |
| `TRANSFORMER_STRONG_EDGE_MULTIPLIER` | `1.5` | Legacy edge multiplier (execution plan STRONG sizing) |
| `TRANSFORMER_EXTREME_REGIME_VETO` | `true` | Climate EXTREME → crisis HOLD in synthesis |
| `TRANSFORMER_ENTRY_GATES` | `true` | Safety-only trading handler (no legacy feature vetoes) |
| `LEGACY_FEATURE_ENTRY_GATES` | `false` | Emergency rollback for ADX/EMA/BB/SR filters |
| `SL_TP_MODE` | `atr` | Duration-scaled ATR (fusion); `path_pred` for synthesis rollback |
| `PATH_SL_ADVERSE_MULT` | `1.0` | Stop distance × adverse excursion |
| `PATH_TP_FAVORABLE_MULT` | `1.0` | Take-profit × favorable excursion |
| `PATH_RR_SIZE_FACTOR` | `0.7` | Soft R:R size cut (never hard-rejects) |
| `TRANSFORMER_SIZE_FLOOR` | `0.35` | Min size_scale clip |
| `TRANSFORMER_SIGNAL_THRESHOLD` | *(from metadata)* | Optional override of `default_threshold` |
| `MODEL_DISCOVERY_ENABLED` | `true` | Enable startup discovery |
| `MODEL_AUTO_REGISTER` | `true` | Register discovered node in MCP registry |

See [Deployment – Agent environment variables](10-deployment.md#agent-environment-variables).

---

## Training and export

Train the **live fused v11 model** is frozen. The research trainer now trains **Label V2 / v15** four 3-class heads. The current pass is **later_direction_only**: path SmoothL1 weights are 0 and `use_class_weights` is False. Path heads stay on the ONNX graph but are not trained. After that train, **direction predictability** is a CPU last-bar bake-off (`--score-test --ablate-groups`). **Path-edge regression** is a separate last-bar experiment (`--path-regression`): signed `(long_mfe-long_mae)-(short_mfe-short_mae)`, not 3-class CE and not a fused retrain. Do not copy the export into `agent/model_storage/`:

```bash
python scripts/colab/train_mtf_fusion.py --export-dir export/mtf_fusion_v15
```

Export lands in `export/mtf_fusion_v15/JackSparrow_Transformer_BTCUSD_mtf_fusion_v15/`. `fusion_ready_to_promote` is always `ready=false` (`research_v15_not_live`). Live remains `JackSparrow_Transformer_BTCUSD_mtf_fusion` (v11).

Walk-forward and Optuna (if enabled) never see the final test split. Per-horizon HIGH/MEDIUM/LOW grades are research telemetry only on v15.

The legacy per-TF trainer remains for rollback bundles only:

```bash
python scripts/colab/train_transformer_resolution.py --all --export-dir export --continue-on-error
```

Exports auto-generate `metadata_transformer.json`, `btcusd_{tf}_transformer.onnx`, and `feature_config.json`.

**Tests before deploy:**

```bash
pytest tests/unit/test_mtf_asof_alignment.py \
       tests/unit/test_mtf_fusion_labels.py \
       tests/unit/test_mtf_fusion_model.py \
       tests/unit/test_mtf_fusion_decision.py \
       tests/unit/test_mtf_fusion_features.py \
       tests/unit/test_transformer_decision.py \
       tests/unit/test_forecast_30m_v5.py \
       tests/unit/test_forecast_decision.py \
       tests/integration/test_agent_synthesis_decision.py \
       tests/integration/test_mtf_transformer_decision.py -q
```

---

## Model discovery and registration

Runtime-critical modules:

| Path | Role |
|------|------|
| `agent/models/model_discovery.py` | Forecast bundle on `forecast_30m`; fused bundle otherwise; per-TF only on rollback |
| `agent/models/forecast_node.py` | `ForecastModelNode` (joblib v5 direction head) |
| `agent/models/fusion_node.py` | `FusionModelNode` (ONNX via onnxruntime) |
| `agent/models/transformer_node.py` | Per-TF node (emergency synthesis only) |
| `agent/core/forecast_policy.py` | Class map, 12-hour lock, ATR brackets |
| `agent/core/fusion_policy.py` | Per-horizon gates + duration |
| `agent/core/transformer_decision.py` | Slim decision path → `PolicyVerdict` / `DECISION_READY` |
| `agent/core/mcp_orchestrator.py` | Orchestrates features → model → decision |

Decision flow (`forecast_30m`, when a promoted bundle is present):

1. `CANDLE_CLOSED` (5m) → fetch independent frames; inference uses closed 30m
2. `ForecastModelNode.predict()` runs the v5 XGBoost direction head
3. Argmax BEARISH / BULLISH maps to SELL / BUY when probability clears the frozen floor; NEUTRAL is HOLD
4. A new entry is skipped while a 12-hour forecast position is reserved; ATR SL/TP; `decision_path=forecast_30m`
5. `DECISION_READY` → trading handler → risk → execution

Decision flow (`mtf_fusion` rollback):

1. `CANDLE_CLOSED` (5m) → fetch independent 5m/10m/30m/1h/2h frames
2. `FusionModelNode.predict()` runs the fused ONNX graph
3. `evaluate_horizon_forecast()` drops NEUTRAL / LOW-grade / low-probability heads
4. Duration = longest accepted same-side horizon; ATR SL/TP; `decision_path=mtf_fusion`
5. `DECISION_READY` → trading handler → risk → execution

5m never trades alone; it only contributes `Z_5`. A LOW 2h head emits HOLD for that horizon.

See [Logic & reasoning](05-logic-reasoning.md) and [Architecture](01-architecture.md).

---

## Docker

**Production compose** (`docker-compose.yml`):

- Bind mount: `./agent/model_storage:/app/agent/model_storage`
- Default `MODEL_DIR` → `/app/agent/model_storage`; live bundle is `JackSparrow_Forecast_BTCUSD_30m/`
- `TRANSFORMER_DECISION_PATH=forecast_30m` (rollback: `mtf_fusion`)
- Rebuild agent image for code or `research/` changes; model-only updates need container recreate:

```bash
docker compose up -d --force-recreate agent
```

**Application code changes** require image rebuild:

```bash
docker compose build agent
docker compose up -d --force-recreate agent
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `model_discovery_transformer_missing` | `metadata_transformer.json` present under `MODEL_DIR` |
| `model_discovery_artifact_missing` | ONNX + `feature_config.json` in bundle dir |
| No trades / all HOLD | Inspect `market_context.market_state` (`climate`/`setup`/`timing`); ranging, conflicted, crisis, timing-against, and flat 15m setup all HOLD by design |
| Feature parity errors | `pytest tests/unit/test_transformer_btcusd_per_tf.py` |
| Stale model after Colab export | Restart agent; verify bind mount path in Docker |

Scan logs for `model_discovered_transformer`, `transformer_decision`, and `trading_entry_rejected`.

---

## Archived inference families

Previous branches used rule-based IC (`metadata_ic.json`), v43 XGBoost pickles, v15 pipelines, and multi-model ensembles. Those paths were removed on the **Transformers** branch. Historical specs remain under [`reference/`](../reference/) for forks.

Do **not** point `MODEL_DIR` at archived bundle folders expecting them to load — discovery accepts transformer bundles only.

---

## Research: 15-minute recognition

`research/recognition_15m/` trains geometric families and market state from 48 completed 15-minute BTCUSD bars. Model discovery loads `agent/model_storage/JackSparrow_Recognition_BTCUSD_15m/tcn_colab.pt` and attaches that readout to the forecast decision. It is not a `ForecastModelNode`. The live order path remains `forecast_30m`.

The track reads 48 completed 15-minute BTCUSD bars. Inputs are raw OHLCV scaled inside the window, or candle geometry derived from those bars. Candle-rule columns (`cdl_*`), chart-rule columns, forecast labels, and future returns are rejected before training. Textbook names such as hammer and hanging man are stored on a separate rule card and are not model classes. Head A learns geometric families. Head E learns the window's market state from swings confirmed inside the window. Chart patterns, formation status, breakouts, and zone geometry are specified and not trained.

Chronological splits leave a purge of 48 bars between train, validation, and test. The contract is [`reference/recognition-15m-spec.md`](../reference/recognition-15m-spec.md). Train the short local fit with `python -m research.recognition_15m`. Metrics land in `export/recognition_15m/metrics.json`. The agent loads the Colab checkpoint from model storage and keeps the forecast bundle as the order source.

The intense fit is the generated notebook `scripts/colab/recognition_15m_colab.ipynb`. Upload that notebook to Colab and run the cells from top to bottom. The training code is in the notebook, so the runtime does not clone this repository. It runs a purged Optuna search on the development span, a train-only Spearman audit, and TreeSHAP of the presence baseline, then refits one TCN and scores the sealed test once. The report in the Colab output folder records class-wise recognition metrics, Head A calibration, the correlation matrix, the SHAP ranking, the purge gaps, and the winning trial. The same folder holds PNG figures for the train and validation loss, validation against the sealed test, the Optuna trials, the correlation heatmaps, the SHAP ranking, and Head A reliability. The notebook draws those figures after the fit. It does not record a buy, a sell, expectancy, Sharpe, or a promotion flag. The agent copies that checkpoint into model storage and reads it as decision context.

---

## Related documentation

- [Architecture](01-architecture.md) — three-tier design and data flow
- [MCP layer](02-mcp-layer.md) — feature/model protocols
- [Logic & reasoning](05-logic-reasoning.md) — transformer decision path
- [Deployment](10-deployment.md) — env vars and Docker
- [Build guide](11-build-guide.md) — setup and tests
- [`.cursor/rules/ml-model-management.mdc`](../.cursor/rules/ml-model-management.mdc) — Cursor rule for transformer standards
- [Label V2 spec (research)](../reference/label-v2-spec.md) — path targets; live v11 2-class fusion is unchanged
- [15-minute recognition spec (research)](../reference/recognition-15m-spec.md) — geometric labels only; live `forecast_30m` is unchanged
