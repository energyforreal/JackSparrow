# ML Model Management Documentation

## Overview

On branch **Transformers**, JackSparrow loads **per-timeframe ONNX Transformer bundles** (5m, 15m, 30m, 1h, 2h). `ModelDiscovery` registers one `TransformerModelNode` per bundle; the MCP orchestrator runs all models and applies `evaluate_mtf_policy` in `agent/core/mtf_decision_policy.py` via `evaluate_transformer_prediction` in `agent/core/transformer_decision.py` to produce `DECISION_READY` events.

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

Point **`MODEL_DIR`** at **`agent/model_storage/`** (parent directory). Each per-TF bundle lives in a subdirectory:

`JackSparrow_Transformer_BTCUSD_{5m,15m,30m,1h,2h}/`

Required artifacts per bundle:

| File | Purpose |
|------|---------|
| `metadata_transformer.json` | Bundle manifest (resolution, thresholds, ONNX filename) |
| `btcusd_{tf}_transformer.onnx` | ONNX model (loaded via `onnxruntime`) |
| `feature_config.json` | Feature names and train/serve parity config |

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
├── JackSparrow_Transformer_BTCUSD_5m/
├── JackSparrow_Transformer_BTCUSD_15m/
├── JackSparrow_Transformer_BTCUSD_30m/
├── JackSparrow_Transformer_BTCUSD_1h/
└── JackSparrow_Transformer_BTCUSD_2h/
```

Each subdirectory contains `metadata_transformer.json`, `btcusd_{tf}_transformer.onnx`, and `feature_config.json`.

Default in [`agent/core/config.py`](../agent/core/config.py):

```bash
MODEL_DIR=./agent/model_storage
```

---

## Feature contract

Train/serve parity lives in [`feature_store/transformer_btcusd/`](../feature_store/transformer_btcusd/):

- `contract.py` — per-TF resolutions, single `future_return` label
- `features.py`, `derivatives.py` — native TF feature matrix
- `inference.py` — ONNX input assembly + metadata export
- `labels.py` — training label helpers (Colab)

Each `TransformerModelNode` builds features on its native TF grid only.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIR` | `./agent/model_storage` | Parent directory for per-TF bundles |
| `TRANSFORMER_EXECUTION_TFS` | `15m,30m` | Execution anchor TFs for MTF policy |
| `TRANSFORMER_BIAS_TFS` | `1h,2h` | Bias/veto TFs |
| `TRANSFORMER_TIMING_TF` | `5m` | Timing modifier TF |
| `TRANSFORMER_MIN_TF_ALIGNMENT` | `3` | Min aligned TFs for STRONG signals |
| `TRANSFORMER_MIN_CONFIDENCE` | `0.55` | Minimum confidence for entry signals |
| `TRANSFORMER_STRONG_EDGE_MULTIPLIER` | `1.5` | Edge multiplier for STRONG_BUY/SELL |
| `TRANSFORMER_EXTREME_REGIME_VETO` | `true` | Force HOLD when vol regime is EXTREME |
| `TRANSFORMER_SIGNAL_THRESHOLD` | *(from metadata)* | Optional override of `default_threshold` in metadata |
| `MODEL_DISCOVERY_ENABLED` | `true` | Enable startup discovery |
| `MODEL_AUTO_REGISTER` | `true` | Register discovered node in MCP registry |
| `MIN_CONFIDENCE_THRESHOLD` | `0.70` | Execution gate (trading handler) |

See [Deployment – Agent environment variables](10-deployment.md#agent-environment-variables).

---

## Training and export

Train each TF **independently** (no cross-TF fusion):

| Notebook | Resolution |
|----------|------------|
| `scripts/colab/transformer_btcusd_5m_train.ipynb` | 5m |
| `scripts/colab/transformer_btcusd_15m_train.ipynb` | 15m |
| `scripts/colab/transformer_btcusd_30m_train.ipynb` | 30m |
| `scripts/colab/transformer_btcusd_1h_train.ipynb` | 1h |
| `scripts/colab/transformer_btcusd_2h_train.ipynb` | 2h |

Or via CLI: `python scripts/colab/train_transformer_resolution.py --resolution 15m --export-dir export/15m`

Exports auto-generate `metadata_transformer.json`, `btcusd_{tf}_transformer.onnx`, and `feature_config.json`.

**Tests before deploy:**

```bash
pytest tests/unit/test_transformer_btcusd_per_tf.py \
       tests/unit/test_mtf_decision_policy.py \
       tests/unit/test_transformer_decision.py \
       tests/unit/test_transformer_model_discovery.py -q
```

---

## Model discovery and registration

Runtime-critical modules:

| Path | Role |
|------|------|
| `agent/models/model_discovery.py` | Transformer-only discovery |
| `agent/models/transformer_node.py` | `TransformerModelNode` (ONNX via onnxruntime) |
| `agent/models/transformer_context_builder.py` | Maps prediction → signal context |
| `agent/models/mcp_model_registry.py` | MCP model registry |
| `agent/core/transformer_decision.py` | Slim decision path → `PolicyVerdict` / `DECISION_READY` |
| `agent/core/mcp_orchestrator.py` | Orchestrates features → model → decision |

Decision flow:

1. `CANDLE_CLOSED` / price trigger → fetch 5m/15m/30m/1h/2h frames
2. Each `TransformerModelNode.predict()` runs ONNX on its native TF
3. `evaluate_mtf_policy()` applies layered rules (bias → execution → alignment → timing → veto)
4. `evaluate_transformer_prediction()` emits BUY/SELL/HOLD + confidence
5. `DECISION_READY` → trading handler → risk → execution

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
| No trades / all HOLD | `TRANSFORMER_MIN_CONFIDENCE`, `TRANSFORMER_EXTREME_REGIME_VETO`, `MIN_CONFIDENCE_THRESHOLD` |
| Feature parity errors | `pytest tests/unit/test_transformer_btcusd_15m.py` |
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
