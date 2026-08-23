# ML Model Management Documentation

## Overview

JackSparrow’s live path is **one fused multi-TF Transformer** (`JackSparrow_Transformer_BTCUSD_mtf_fusion`). Independent OHLCV for 5m / 10m / 30m / 1h / 2h is encoded by a shared encoder, fused with learned softmax weights, then four 3-class heads forecast **+10m / +30m / +1h / +2h** as BULL / NEUTRAL / BEAR. [`agent/core/fusion_policy.py`](../agent/core/fusion_policy.py) applies frozen walk-forward grades and does **not** pick the highest probability. Trade duration is the longest accepted same-side horizon. SL/TP is ATR-scaled to that duration.

Emergency rollback: `TRANSFORMER_DECISION_PATH=transformer_agent_synthesis` reloads the five per-TF ONNX bundles and climate/setup/timing synthesis. That path is not dual-running by default.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Runtime discovery (Transformer ONNX)](#runtime-discovery-transformer-onnx)
- [Bundle layout](#bundle-layout)
- [Feature contract](#feature-contract)
- [Environment variables](#environment-variables)
- [Training and export](#training-and-export)
- [Model discovery and registration](#model-discovery-and-registration)
- [Docker](#docker)
- [Troubleshooting](#troubleshooting)
- [Archived inference families](#archived-inference-families)
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

## Bundle layout

```
agent/model_storage/
└── JackSparrow_Transformer_BTCUSD_mtf_fusion/
    ├── metadata_transformer.json
    ├── btcusd_mtf_fusion.onnx
    └── feature_config.json
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

- `contract.py` — per-TF resolutions, path labels only (MFE/MAE/vol/trend/OI/volume); no `future_return` head
- `features.py`, `derivatives.py` — native TF feature matrix
- `inference.py` — ONNX input assembly + metadata export
- `labels.py` — training label helpers (Colab)

Each `TransformerModelNode` builds features on its native TF grid only.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIR` | `./agent/model_storage` | Parent directory for model bundles |
| `TRANSFORMER_DECISION_PATH` | `mtf_fusion` | Live path; `transformer_agent_synthesis` is emergency rollback |
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

Train the **single fused model** (independent 5m/10m/30m/1h/2h encodings, walk-forward on the development span, untouched test):

```bash
python scripts/colab/train_mtf_fusion.py --export-dir export/mtf_fusion
```

Copy `export/mtf_fusion/JackSparrow_Transformer_BTCUSD_mtf_fusion/` into `agent/model_storage/`.

Walk-forward and Optuna (if enabled) never see the final test split. Per-horizon HIGH/MEDIUM/LOW grades are frozen in `feature_config.json`.

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
       tests/integration/test_agent_synthesis_decision.py \
       tests/integration/test_mtf_transformer_decision.py -q
```

---

## Model discovery and registration

Runtime-critical modules:

| Path | Role |
|------|------|
| `agent/models/model_discovery.py` | Prefers fused bundle; per-TF only on rollback |
| `agent/models/fusion_node.py` | `FusionModelNode` (ONNX via onnxruntime) |
| `agent/models/transformer_node.py` | Per-TF node (emergency synthesis only) |
| `agent/core/fusion_policy.py` | Per-horizon gates + duration |
| `agent/core/transformer_decision.py` | Slim decision path → `PolicyVerdict` / `DECISION_READY` |
| `agent/core/mcp_orchestrator.py` | Orchestrates features → model → decision |

Decision flow:

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
- Default `MODEL_DIR` → `JackSparrow_Transformer_BTCUSD` inside the container
- Rebuild agent image only for **code** changes; model-only updates need container recreate:

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

## Related documentation

- [Architecture](01-architecture.md) — three-tier design and data flow
- [MCP layer](02-mcp-layer.md) — feature/model protocols
- [Logic & reasoning](05-logic-reasoning.md) — transformer decision path
- [Deployment](10-deployment.md) — env vars and Docker
- [Build guide](11-build-guide.md) — setup and tests
- [`.cursor/rules/ml-model-management.mdc`](../.cursor/rules/ml-model-management.mdc) — Cursor rule for transformer standards
