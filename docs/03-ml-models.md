# ML Model Management Documentation

## Overview

On branch **Transformers**, JackSparrow loads a single **ONNX Transformer** bundle for runtime inference. `ModelDiscovery` registers `TransformerModelNode`; the MCP orchestrator calls `evaluate_transformer_prediction` in `agent/core/transformer_decision.py` to produce `DECISION_READY` events.

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

Point **`MODEL_DIR`** at **`agent/model_storage/JackSparrow_Transformer_BTCUSD/`**. Required artifacts:

| File | Purpose |
|------|---------|
| `metadata_transformer.json` | Bundle manifest (horizons, thresholds, ONNX filename) |
| `btcusd_15m_transformer.onnx` | ONNX model (loaded via `onnxruntime`) |
| `feature_config.json` | Feature names and train/serve parity config |

`ModelDiscovery.discover_models()` in [`agent/models/model_discovery.py`](../agent/models/model_discovery.py):

1. Resolves `metadata_transformer.json` under `MODEL_DIR`
2. Verifies ONNX and `feature_config.json` exist
3. Instantiates `TransformerModelNode.from_metadata_path()`
4. Registers the node when `MODEL_AUTO_REGISTER=true`
5. Logs **`model_discovered_transformer`** on success

**`MODEL_PATH` is ignored** — use `MODEL_DIR` only.

---

## Bundle layout

```
agent/model_storage/JackSparrow_Transformer_BTCUSD/
├── metadata_transformer.json
├── btcusd_15m_transformer.onnx
├── feature_config.json
└── README.md
```

Default in [`agent/core/config.py`](../agent/core/config.py) and [`.env.example`](../.env.example):

```bash
MODEL_DIR=./agent/model_storage/JackSparrow_Transformer_BTCUSD
```

Docker Compose (`docker-compose.yml`) sets:

```yaml
MODEL_DIR: ${AGENT_MODEL_DIR:-/app/agent/model_storage/JackSparrow_Transformer_BTCUSD}
```

---

## Feature contract

Train/serve parity lives in [`feature_store/transformer_btcusd_15m/`](../feature_store/transformer_btcusd_15m/):

- `contract.py` — metadata/onnx/feature_config filenames
- `features.py`, `htf_features.py` — runtime feature matrix
- `inference.py` — ONNX input assembly
- `labels.py` — training label helpers (Colab)

The feature server and `TransformerModelNode.predict()` use the same contract as the Colab notebook.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_DIR` | `./agent/model_storage/JackSparrow_Transformer_BTCUSD` | Transformer bundle directory |
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

1. Train in Colab: [`scripts/colab/transformer_btcusd_15m_train.ipynb`](../scripts/colab/transformer_btcusd_15m_train.ipynb)
2. Download `btcusd_15m_transformer.onnx` and `feature_config.json` into the bundle directory
3. `metadata_transformer.json` is committed as the manifest; update horizons/thresholds after retrain if needed
4. Optional local export helper: [`scripts/export_minimal_transformer_bundle.py`](../scripts/export_minimal_transformer_bundle.py)

**Tests before deploy:**

```bash
pytest tests/unit/test_transformer_btcusd_15m.py \
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

1. `CANDLE_CLOSED` / price trigger → feature request
2. Feature server builds transformer feature matrix
3. `TransformerModelNode.predict()` runs ONNX inference
4. `evaluate_transformer_prediction()` maps output to BUY/SELL/HOLD + confidence
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
