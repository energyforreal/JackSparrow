# ML Model Management Documentation

## Overview

This document describes how intelligence bundles are managed, discovered, and integrated into **JackSparrow's** AI reasoning system. On branch **NO-ML**, runtime uses the **Intelligence Component (IC)** — rule-based signals with the v43 feature contract — not pickle-based XGBoost inference. Archived ML training and v43 bundle sections remain for reference and forks.

**Repository**: [https://github.com/energyforreal/JackSparrow](https://github.com/energyforreal/JackSparrow)

---

## Table of Contents

- [Overview](#overview)
- [Model Directory Structure](#model-directory-structure)
- [Model Upload Process](#model-upload-process)
- [Model Discovery and Registration](#model-discovery-and-registration)
- [AI Agent Model Intelligence](#ai-agent-model-intelligence)
- [Model Versioning and Management](#model-versioning-and-management)
- [Custom Model Integration](#custom-model-integration)
- [Model Performance Tracking](#model-performance-tracking)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [Related Documentation](#related-documentation)

---

## Runtime discovery (NO-ML: Intelligence Component)

Point **`MODEL_DIR`** at **`agent/model_storage/JackSparrow_IC_BTCUSD/`** containing **`metadata_ic.json`** only (no `.pkl` artifacts). Set **`IC_MODE=true`** (default). **`ModelDiscovery`** registers **`RuleBasedIntelligenceNode`** from [`agent/intelligence/ic_node.py`](../agent/intelligence/ic_node.py). Features are computed at runtime via [`feature_store/jacksparrow_v43_build_matrix.py`](../feature_store/jacksparrow_v43_build_matrix.py); policy fusion uses **`AGENT_POLICY_MODE=ml_or_thesis`** with **`REQUIRE_ML_SIGNAL_FOR_ORDERS=false`** for paper/live without legacy ML guards.

### Archived: JackSparrow v43 XGBoost + MSO v50

The following applied before branch **`NO-ML`** and is retained for historical reference only.

### MSO v50 (market-state oracle)

- **Family:** `market_state_oracle_v50`
- **Artifacts:** `metadata_mso_v50.json`, `model_artifact_mso_v50.pkl`
- **Output:** structured `market_state` dict per horizon (trend, vol, breakout, liquidity, momentum, compression)
- **Training:** [`notebooks/jacksparrow_mso_v50_training.ipynb`](../notebooks/jacksparrow_mso_v50_training.ipynb) (branch `MAJOR-REWORK-2`)
- **Policy:** `synthesize_market_state_intelligence()` in [`agent/core/agent_policy_engine.py`](../agent/core/agent_policy_engine.py)

### v43 (scalar gate — primary)

Point **`MODEL_DIR`** at the bundle directory containing **`metadata_v43.json`** and the model artefacts (see `JackSparrow_v43_models_BTCUSD/` layout below). **`ModelDiscovery`** registers a single **`JackSparrowV43Node`** loading one **`MultiHeadBundle`** with four intraday heads (`scalp_10m` 2 bars, `intraday_30m` 6, `trend_1h` 12, `swing_2h` 24). Legacy single-horizon (`training_forward_bars=120`) bundles are rejected at metadata validation. Train/export via `notebooks/jacksparrow_v43_delta_india_training.ipynb` or `scripts/train_v43_multihead_export.py`. **`MODEL_PATH` is ignored** (see [`agent/models/model_discovery.py`](../agent/models/model_discovery.py)). Sections that describe **`metadata_BTCUSD_*.json`**, **`PipelineV15Node`**, or multi-node v5 loaders are retained as **historical training and parity references** unless you revive that code path locally.

---

## Model Storage Overview

JackSparrow ships bundles under **`agent/model_storage/`**. On branch **NO-ML**, startup discovers **`metadata_ic.json`** in **`MODEL_DIR`** and registers **`RuleBasedIntelligenceNode`**. Archived v43 pickle bundles remain on disk for reference but are not loaded by current discovery.

### `agent/models` layout (NO-ML branch)

Current runtime-critical paths:

- **`agent/intelligence/`** — IC modules + **`ic_node.py`** (`RuleBasedIntelligenceNode`)
- **`agent/models/model_discovery.py`** — IC discovery via **`metadata_ic.json`**
- **`agent/models/mcp_model_registry.py`**, **`mcp_model_node.py`**

Removed on **NO-ML**: v43 node modules, pickle shims, training notebooks, and generic **`xgboost_node`** / **`advanced_consensus`** loaders (see git history on branch **`NO-ML`**).

Legacy compatibility wrappers that are currently redundant in this checkout:

| File | Current status | Reason |
|------|----------------|--------|
| `agent/models/robust_ensemble_node.py` | Removed | Legacy shim removed on 2026-04-01 (target `scripts/` module missing, no in-repo imports). |
| `agent/models/ensemble_signal_bridge.py` | Removed | Legacy shim removed on 2026-04-01 (target `scripts/` module missing, no in-repo imports). |
| `agent/models/regime_classifier.py` | Removed | Legacy shim removed on 2026-04-01 (target `scripts/` module missing, no in-repo imports). |
| `agent/models/lightgbm_node.py` | Removed | Legacy generic node removed on 2026-04-01; active runtime path is metadata-driven v4/consolidated nodes. |
| `agent/models/random_forest_node.py` | Removed | Legacy generic node removed on 2026-04-01; active runtime path is metadata-driven v4/consolidated nodes. |
| `agent/models/lstm_node.py` | Removed | Legacy generic node removed on 2026-04-01; active runtime path is metadata-driven v4/consolidated nodes. |
| `agent/models/transformer_node.py` | Removed | Legacy generic node removed on 2026-04-01; active runtime path is metadata-driven v4/consolidated nodes. |

Operational guidance:

1. Keep these shims only if you still need backward import compatibility for external tooling not tracked in this repo.
2. If no external dependency remains, remove these three wrapper files to reduce dead paths and startup/path-mutation risk.
3. If compatibility is required, replace wrapper indirection with first-class modules under `agent/models/` and stop mutating `sys.path` at import time.

### Training Authority and Train-Serve Parity

There are **four** training/export families documented here. **Deployed inference on branch NO-ML loads family D (IC)**. Family **C (v43 XGBoost)** is archived.

**A — v15 full pipeline (5m / 15m, XGBoost sklearn pipeline per TF)**  
- **Notebook**: removed from `notebooks/` (archival); parity rules below still apply if you keep v15 artefacts under `agent/model_storage/`.  
- **Typical bundle**: `agent/model_storage/jacksparrow_v15_BTCUSD_<date>/{5m,15m}/` with `metadata_BTCUSD_*.json` and `pipeline_{timeframe}_v14.pkl` (filename still uses `_v14`; `model_version` in JSON may also read `v14`).  
- **Features**: Exactly **20** names per timeframe, frozen at export (training sorts the stability-passed set for deterministic order).  
- **Parity**: `metadata_*.json` `features` must match `V15_FEATURES_5M` / `V15_FEATURES_15M` in `feature_store/feature_registry.py` for that TF—same names and order. Inference builds rows in `feature_store/v15_feature_compute.py` and the feature server’s v15 path in `agent/data/feature_server.py`.  
- **Checks**: `pytest tests/unit/test_v15_feature_registry.py`; `pytest tests/unit/test_feature_parity.py` (UnifiedFeatureEngine guardrails); `python scripts/test_model_inference.py --model-dir <bundle>` when possible.

**B — v4 / v5 / v6 expanded-feature bundles (joblib entry/exit or consolidated)**  
- **Notebooks**: historical Colab flows were removed from `notebooks/`; expanded-feature parity remains documented here if you revive old bundles.  
- These use `UnifiedFeatureEngine`, validate coverage against `EXPANDED_FEATURE_LIST` / registry, fee-aware TP/SL labeling, and export timeframe artefacts (`entry_*`, `exit_*`, scaler files, `features_*.json`, `metadata_*.json`) per bundle style.

**C — JackSparrow v43 regression bundle (archived — pre-NO-ML)**  
- **Notebook / export**: `notebooks/jacksparrow_v43_delta_india_training.ipynb` (Delta Exchange India historical candles, `V43_CANONICAL_FEATURES` + contract-aligned export).  
- **Typical bundle**: `agent/model_storage/JackSparrow_v43_models_BTCUSD/` — flat folder with **`metadata_v43.json`**, **`model_artifact_v43.pkl`** (basename override **`JACKSPARROW_V43_ARTIFACT_BASENAME`**), optional `feature_engineer.pkl`, **`regime_models_v43.pkl`**.  
- **Training labels**: Per-head simple forward returns on **5m** candles for **2 / 6 / 12 / 24** bars (`horizons{}` in metadata). **`metadata.features`** matches **`V43_CANONICAL_FEATURES`** (**40** names, fixed order) in **`feature_store/jacksparrow_v43_contract.py`**; MCP alignment in **`feature_store/jacksparrow_v43_mcp_row.py`**.  
- **Promotion metadata**: `model_family=jacksparrow_v43_multihead`, non-empty `horizons{}` with per-head `validation_metrics` (including `dynamic_threshold`), `primary_execution_horizon_bars` (default **6**), `split`, `data`, `provenance`. Legacy **`training_forward_bars=120`** single-head bundles are rejected.  
- **Training notebook hardening**: Colab §1 clones **`major-rework`**; Delta `GET` uses **retry with exponential backoff**; **XGBoost** uses **`early_stopping_rounds`**; §4c trains meta + calibrator and **recomputes P75/P25 thresholds on the meta-stack path**; §4b walk-forward reports **P75 threshold stability** (CoV).  
- **Pattern 3 meta-stacking (§4c)**: (1) base **regressors** (LGBM + XGB + RF) → stacked features; (2) **LGBMClassifier** `ensemble.meta` → direction probability; (3) **Ridge** `ensemble.calibrator` → expected-return scale for gate-5. **`EnsembleModel.predict()`** in [`agent/models/v43_pickle_shims.py`](../agent/models/v43_pickle_shims.py) feeds the calibrator **2D** input (`reshape(-1, 1)`) and clips output to **[-0.10, 0.10]**. Without `calibrator`, raw meta probabilities must not reach the gates.  
- **Promotion checklist (Pattern 3, multi-head)**: each `horizons.{key}.validation_metrics` uses `inference_path` = `"meta_calibrator"`. **Colab default export**: `V43_EXPORT_GATES_STRICT=true` + `V43_EXPORT_STRICT_PRIMARY_ONLY=true` — strict mins on scalp_10m (**0.54**) and intraday_30m (**0.53**); trend_1h/swing_2h only require meta_auc ≥ **0.50** (warnings if below aspirational 0.58/0.60). **Full strict** (all four heads at production mins): set `V43_EXPORT_STRICT_PRIMARY_ONLY=false`. Training labels use **cost-aware** suppression with horizon cost scale on 1h/2h. Gross hit rates remain **warnings**, not hard blocks.  
- **Runtime**: **`JackSparrowV43Node`**, gated path in **`agent/core/mcp_orchestrator.py`** + **`agent/core/v43_signal_gates.py`**. **`v43_df5m`** and **`v43_df_funding`** must be real `pandas.DataFrame` instances; **`v43_df15m`** / **`v43_df1h`** may be omitted or **`None`** (normalized to empty frames)—`build_v43_feature_matrix` resamples higher timeframes from **5m** only, so those frames are optional for inference. Optional **`JACKSPARROW_V43_SHORT_EXECUTION_ENABLED=true`** allows symmetric SHORT firing when negatives pass gates (see `.env.example`). Operational tuning: [v43 trade execution runbook](v43_trade_execution_runbook.md) and **`scripts/analyze_v43_gate_rejects.py`**.  
- **Checks**: `pytest tests/unit/test_jacksparrow_v43_contract.py tests/unit/test_jacksparrow_v43_mcp_row.py` (contract/matrix parity); historical v43 node tests removed on **NO-ML**.

**D — Intelligence Component (IC — Compose / NO-ML default)**  
- **Bundle**: `agent/model_storage/JackSparrow_IC_BTCUSD/` — **`metadata_ic.json`** only (four horizon heads: `scalp_10m`, `intraday_30m`, `trend_1h`, `swing_2h`).  
- **Runtime**: **`RuleBasedIntelligenceNode`** when **`IC_MODE=true`**; policy via **`AGENT_POLICY_MODE=ml_or_thesis`** and **`REQUIRE_ML_SIGNAL_FOR_ORDERS=false`**.  
- **Features**: **`build_v43_feature_matrix`** + **`V43_CANONICAL_FEATURES`**; gates in **`agent/core/v43_signal_gates.py`**.  
- **Checks**: `pytest tests/unit/test_intelligence_ic_node.py tests/unit/test_intelligence_ic_signals.py tests/unit/trading_agent_tests/test_model_discovery.py -q`.

Parity requirements before deployment (family **B**, historical artefacts):

1. `MODEL_DIR` must point to the exact export directory containing `metadata_BTCUSD_*.json`.
2. Metadata `features` and `features_required` must match what that training run emitted—typically aligned with `feature_store/feature_registry.py` `EXPANDED_FEATURE_LIST` in order and length for expanded bundles.
3. Run `tests/unit/test_feature_parity.py` and review pattern-feature importances from the notebook report outputs where applicable.

Legacy notebook variants were removed during the 2026-04 / **NO-ML** cleanups. For **deployed inference** ship **family D (IC)**. Families **A** and **B** remain useful for archival bundles and optional **v15 adaptive retrain** parquet flows. Family **C** is documented for forks that still load v43 pickles.

### Model Storage Location

| Location | Purpose | Environment Variable | Usage |
|----------|---------|---------------------|-------|
| `agent/model_storage/` | All trained ML models | `MODEL_DIR` (points to directory) | Automatic model discovery and registration |

**Bundles on disk:**

| Directory | Role |
|-----------|------|
| `agent/model_storage/JackSparrow_IC_BTCUSD/` | **`MODEL_DIR` for production (NO-ML)** — `metadata_ic.json` only; **RuleBasedIntelligenceNode** (Docker Compose defaults this path in-container unless `AGENT_MODEL_DIR` overrides). |
| `agent/model_storage/JackSparrow_v43_models_BTCUSD/` | **Archived** v43 XGBoost bundle (`metadata_v43.json` + pickles) — not loaded by current discovery. |
| `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19/` | **Historical** full v5 BTCUSD bundle (when present): five horizons (15m–4h) with entry + exit joblib artefacts per timeframe. Not loaded by current discovery. |
| `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21/` | **Historical** slim bundle: 5m/15m metadata; binary `entry_long` / `entry_short` artifacts; not loaded by current discovery. |
| `agent/model_storage/jacksparrow_v6_BTCUSD_<date>/` | **Historical** v6 unified model bundle — not loaded by current discovery. |
| `agent/model_storage/jacksparrow_v15_BTCUSD_<date>/` | **Historical** v15 full pipeline bundle — **`metadata_BTCUSD_*.json`** + **`pipeline_*_v14.pkl`**; used mainly for parquet-based **adaptive retrain** and archived validation; not loaded as primary inference alongside v43. |

- **`ModelDiscovery.discover_models()`** requires **`MODEL_DIR/metadata_ic.json`** when **`IC_MODE=true`**; logs **`model_discovered_ic`** / **`model_discovery_ic_failed`**. v43 pickle discovery is removed on **NO-ML**.

### Historical: multi-timeframe v5 nodes (legacy)

A **historical full** v5 deployment (bundle `jacksparrow_v5_BTCUSD_2026-03-19` or equivalent) would register **five** v5 BTCUSD timeframe nodes (**not active** under v43 discovery):

- `jacksparrow_BTCUSD_15m`
- `jacksparrow_BTCUSD_30m`
- `jacksparrow_BTCUSD_1h`
- `jacksparrow_BTCUSD_2h`
- `jacksparrow_BTCUSD_4h`

Each model is loaded from `metadata_BTCUSD_<timeframe>.json` and references:
- `entry_model_BTCUSD_<timeframe>.joblib`
- `exit_model_BTCUSD_<timeframe>.joblib`
- `entry_scaler_BTCUSD_<timeframe>.joblib`
- `exit_scaler_BTCUSD_<timeframe>.joblib`
- `features_BTCUSD_<timeframe>.json`

### Environment Configuration

The root `.env` file (documented in [Deployment Documentation](10-deployment.md#environment-variables-reference)) configures model discovery:

```bash
IC_MODE=true
MODEL_DIR=./agent/model_storage/JackSparrow_IC_BTCUSD
AGENT_POLICY_MODE=ml_or_thesis
REQUIRE_ML_SIGNAL_FOR_ORDERS=false
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
MIN_CONFIDENCE_THRESHOLD=0.70
```

`MODEL_DIR` must contain **`metadata_ic.json`** (see [`.env.example`](../.env.example)). **`MODEL_FORMAT`** defaults to **`jacksparrow_ic`** in health payloads.

### ML Models in Docker

When running under Docker, the agent container mounts the host `agent/model_storage/` directory.

- **Bind mount**: `./agent/model_storage:/app/agent/model_storage` (see `docker-compose.yml` agent service).
- **Default in-container `MODEL_DIR`**: Compose sets **`MODEL_DIR=${AGENT_MODEL_DIR:-/app/agent/model_storage/JackSparrow_IC_BTCUSD}`** and **`IC_MODE=true`** unless overridden in the root `.env`.
- **Delta WebSocket**: Compose sets **`WEBSOCKET_URL=${WEBSOCKET_URL:-wss://socket-ind.testnet.deltaex.org}`** on the agent service (socket host, not REST CDN).

To use a different IC bundle folder, set **`AGENT_MODEL_DIR`** to that path inside the bind mount:

```bash
AGENT_MODEL_DIR=/app/agent/model_storage/MyCustom_IC_BTCUSD
```

Then recreate or restart the agent service.

This means:

- Artefacts you place under `agent/model_storage/` on the host are visible in-container without rebuilding images.
- Updating models: copy files on the host, then `docker compose restart agent`.

**Verification steps before `docker compose up`:**

1. Ensure **`metadata_ic.json`** exists under `agent/model_storage/JackSparrow_IC_BTCUSD/` (or your **`AGENT_MODEL_DIR`** target).
2. After `docker compose up`, scan agent logs for **`model_discovered_ic`** (`model_discovery_ic_failed` means metadata or IC init failed).
3. Confirm backend **`/api/v1/health`** shows **`model_format`** ≈ **`jacksparrow_ic`**, **`healthy_models`: 1**, and Delta WSS logs (`delta_websocket_key_auth_sent`; fix IP whitelist if **`delta_websocket_auth_rejected`**).

### XGBoost Dependency Requirements (archived ML path)

- **NO-ML / IC runtime** does not load pickles; **`IC_MODE=true`** uses rule-based inference only.
- The agent Docker image still installs `xgboost`, `tensorflow`, and `torch` from `agent/requirements.txt` (large image) for forks and archival scripts. To slim the image on a pure-IC deployment, trim `agent/requirements.txt` in a dedicated branch.
- When deserializing legacy v43/v15 pickles, keep `xgboost==2.0.2` aligned with the training environment.
- If you rebuild or upgrade the models, ensure `requirements*.txt` stay synchronized with the version used during training.
- When the validator reports `ModuleNotFoundError: No module named 'XGBClassifier'`, re-run `pip install -r agent/requirements.txt` inside the active environment before retrying the load.

### Operational Workflow (bundle-first)

1. Train/export via [`notebooks/jacksparrow_v43_delta_india_training.ipynb`](../notebooks/jacksparrow_v43_delta_india_training.ipynb) on branch **`major-rework`** (Colab §1 clone cell). Download **`jacksparrow_v43_bundle.zip`** (`metadata_v43.json` + `model_artifact_v43.pkl`).
2. **Promote into** [`agent/model_storage/JackSparrow_v43_models_BTCUSD/`](../agent/model_storage/JackSparrow_v43_models_BTCUSD/):
   - Back up existing `metadata_v43.json`, `model_artifact_v43.pkl`, and `model_artifact_v43_patched.pkl` (e.g. rename to `*_old_YYYYMMDD.*`).
   - Copy the two new files from Downloads.
   - From repo root: `python scripts/patch_v43_model_artifact.py` — writes **`model_artifact_v43_patched.pkl`** (runtime default). `patched: false` in script output means thresholds were already correct in the export.
3. Confirm **`metadata_v43.json`**: `inference_path` = `meta_calibrator` when Pattern 3 was used; `validation_corr` > 0; `model_architecture` present. See [v43 runbook — Model promotion gate](v43_trade_execution_runbook.md#model-promotion-gate).
4. Set **`MODEL_DIR`** / **`AGENT_MODEL_DIR`** to the bundle folder; set **`JACKSPARROW_V43_ARTIFACT_BASENAME=model_artifact_v43_patched.pkl`** and tune execution knobs per [v43 trade execution runbook](v43_trade_execution_runbook.md) (see [.env.example](../.env.example)).
5. **Restart the agent**; confirm **`model_discovered_v43`**; run `python scripts/smoke_test_v43.py`, **`pytest tests/unit/test_jacksparrow_v43_*.py tests/unit/test_jack_sparrow_v43_*.py -q`**, and [`jacksparrow_v43_smoke.md`](jacksparrow_v43_smoke.md).
6. (Optional) Commit promoted artefacts to git when you intend the repo to carry the new weights.

**Checked-in production bundle (2026-05-17):** Pattern 3 meta+calibrator; `exported_at` in metadata; runtime loads **`model_artifact_v43_patched.pkl`**. Review `short_threshold` / short-candidate counts in metadata before enabling live shorts.

### Single consolidated model mode (optional cutover — historical)

**Not compatible with v43-only discovery** in [`agent/models/model_discovery.py`](../agent/models/model_discovery.py). Documented here for forks that revive multi-node loaders. If you export a consolidated artefact from a legacy v5 flow, enable single-model mode explicitly in `.env`:

```bash
MODEL_DIR=./agent/model_storage/jacksparrow_v5_BTCUSD_YYYY-MM-DD
SINGLE_MODEL_MODE_ENABLED=true
CONSOLIDATED_MODEL_METADATA_GLOB=metadata_BTCUSD_consolidated*.json
USE_ML_EXIT_MODEL=false
```

Notes:
- `SINGLE_MODEL_MODE_ENABLED=true` is required on branches that still branch discovery on this flag.
- Keep `USE_ML_EXIT_MODEL=false` with current v5 notebook exports (entry-focused, rule-based exits at runtime).

### Learning Control Modules (agent runtime)

The adaptive control loop under `agent/learning/` now uses bounded, production-safe behavior:

- `performance_tracker.py`: tracks both total and evaluated predictions separately so accuracy is calculated only from labeled outcomes; per-model event history is capped.
- `confidence_calibrator.py`: applies reliability scaling with cold-start blending so new models do not collapse confidence to near-zero before enough outcomes exist.
- `model_weight_adjuster.py`: combines reliability and profit with a saturated (`tanh`) profit component to avoid runaway single-model dominance.
- `strategy_adapter.py`: adapts position-size and confidence gate only after a minimum evaluated sample count.
- `threshold_adapter.py` / `dynamic_thresholds.py`: parse and clamp Redis threshold values with finite-number guards; DB fetch paths dispose SQLAlchemy engines after use.
- `threshold_adapter.py`: threshold key updates are emitted in a single Redis transaction and adaptation runs are serialized per process.
- `retraining_scheduler.py`: retrain subprocess execution is serialized per process, retrain triggers use sanitized PnL values, and cooldown/state is persisted with atomic file replace semantics.

#### Runtime adaptive retrain (v15 pipeline, optional)

The agent can run a **separate** path from trade-outcome retraining: KS drift on two recent windows, then **warm-start** `xgb.train(..., xgb_model=old_booster)` with class weights matching notebook Cell 5 (`SELL`/`HOLD`/`BUY` = 1.3 / 0.5 / 1.3), a **macro-F1** holdout gate (`new_f1 >= old_f1 + ADAPTIVE_MIN_F1_IMPROVEMENT`), and versioned artifacts next to each timeframe’s metadata.

| Topic | Detail |
|--------|--------|
| **Code** | `agent/learning/adaptive/` (`drift_detector`, `retrain_engine`, `model_validator`, `model_registry`, `adaptive_controller`, `labeled_data`); tick from `agent/core/intelligent_agent.py` when `ADAPTIVE_RETRAIN_ENABLED=true`. |
| **Artifact load order** | `PipelineV15Node` (`agent/models/pipeline_v15_node.py`) resolves `pipeline_{tf}_latest.pkl` before `pipeline_{tf}_v14.pkl`. **Adaptive retrain** writes into the v15 bundle tree; **`ModelDiscovery` in this repo does not register these nodes during normal v43-only startup.** |
| **Labeled data** | `ADAPTIVE_LABELED_DATA_SOURCE=parquet` and `ADAPTIVE_RETRAIN_PARQUET_DIR` → files `labeled_5m.parquet`, `labeled_15m.parquet` with the same **feature column names and order** as `metadata_BTCUSD_{tf}.json` plus integer `label` in `{0,1,2}`. Minimum row counts follow settings (default ≥ 40k rows for drift windows). |
| **Artifacts** | On accept: `pipeline_{tf}_v_auto_<unix>.pkl` (archive), `pipeline_{tf}_latest.pkl` (pointer), `retrain_log.json` append next to metadata, and `metadata` JSON updated (`train_median`, `adaptive` audit fields). |
| **Cooldown** | Per-TF timestamps in `ADAPTIVE_RETRAIN_STATE_PATH` (respects `LOGS_ROOT` when set). |
| **Hot reload** | After any TF accepts in a tick, `await mcp_orchestrator.refresh_models()` reloads discovery without restarting the process. Programmatic use: `from agent.learning.adaptive.adaptive_controller import hot_reload_models`. |
| **Rollback** | Copy a known-good `pipeline_{tf}_v14.pkl` or versioned pickle over `pipeline_{tf}_latest.pkl`, then trigger a refresh (restart agent or call `hot_reload_models` from an async context). Use `retrain_log.json` to pick a version. |
| **Tests** | `tests/unit/test_adaptive_*.py`, `tests/unit/test_pipeline_v15_resolve_latest.py`. |
| **Env reference** | Root [`.env.example`](../.env.example) and [Deployment – Agent env](10-deployment.md#agent-environment-variables). |

---

## Model Training

### Training (this workspace)

Production **inference** on **NO-ML** uses **`JackSparrow_IC_BTCUSD/metadata_ic.json`** and **`RuleBasedIntelligenceNode`**. Archived **`JackSparrow_v43_models_BTCUSD/`** pickles and training notebooks are documented under [Archived v43](#archived-jacksparrow-v43-xgboost--mso-v50). Older v5/v6/v15 bundles remain for reference or **v15-only** adaptive parquet retrain.

### Prerequisites

Before training models, ensure:
- Delta Exchange API credentials are configured (`.env` file)
- Sufficient historical data is available (script fetches from API)
- Python dependencies are installed: `pip install -r agent/requirements.txt`

### Training Process

1. **Run the training/export notebook** for your target bundle type:
   - **v43 runtime bundle**: `notebooks/jacksparrow_v43_delta_india_training.ipynb`
   - **Historical v15 / v6 / v5**: training notebooks removed from `notebooks/`; see family **A** / **B** sections above for artefact layout if you maintain archival bundles.

2. **Notebook export will** (high level):
   - Fetch historical candles per timeframe (or multi-interval inputs as defined in the notebook)
   - **v43**: Produce **`metadata_v43.json`** + **`model_artifact_v43*.pkl`** with **`features`** order matching **`V43_CANONICAL_FEATURES`** and multi-head **`horizons`** (2/6/12/24 bars).
   - **v15**: Indicator feature engineering inside the notebook (`build_features`), then selection → **20** features per TF in metadata; full sklearn/XGBoost pipeline pickle.
   - **v5/v6**: Compute expanded features via `UnifiedFeatureEngine`, TP/SL-aligned labels (per bundle config), joblib/scaler exports + `metadata_BTCUSD_*.json` in a dated bundle directory.

### Feature counts (important)

- **v43**: **`metadata_v43.json`** **`features`** length is **40**; order must match **`V43_CANONICAL_FEATURES`** (`feature_store/jacksparrow_v43_contract.py`). **Parity tests** lock feature order and multi-head horizon keys.
- **Historical metadata**: **Runtime feature count** for v5/v15 paths was **metadata-defined** (`metadata_BTCUSD_*.json`: `feature_count`, `features`, and/or `features_required`).
- **v15 pipeline bundles** use **20** features per timeframe; names and order must match `V15_FEATURES_5M` / `V15_FEATURES_15M` in `feature_store/feature_registry.py` for the shipped export.
- **Slim v5** bundles in this repo often use on the order of **~126** expanded features—see each `metadata_*.json`.
- The canonical **base** list length for `UnifiedFeatureEngine` is `FEATURE_LIST` in `feature_store/feature_registry.py` (do not rely on ad-hoc “49 features” counts in older prose).

**Price-based (15)**: SMAs (10, 20, 50, 100, 200), EMAs (12, 26, 50), price ratios, candle patterns

**Momentum (10)**: RSI (7, 14), Stochastic (%K, %D), Williams %R, CCI, ROC, Momentum

**Trend (8)**: MACD, MACD signal, MACD histogram, ADX, Aroon (up, down, oscillator), trend strength

**Volatility (8)**: Bollinger Bands (upper, lower, width, position), ATR (14, 20), volatility (10, 20)

**Volume (6)**: Volume SMA, volume ratio, OBV, volume-price trend, accumulation/distribution, Chaikin oscillator

**Returns (2)**: 1h returns, 24h returns

For the full canonical base list, see `FEATURE_LIST` in `feature_store/feature_registry.py` and [Features](04-features.md) for product-level capability overview.

### Model Validation

**Before deployment**, always validate models:
```bash
python scripts/validate_models_before_deployment.py
```

This checks:
- Model files exist and are readable
- Models are XGBClassifier instances (not numpy arrays)
- Models have required methods (`predict`, `predict_proba`)
- Models can make predictions on sample data

**During startup** (optional):
Set `VALIDATE_MODELS_ON_STARTUP=1` in `.env` to validate models before starting the agent.

### Troubleshooting Training

**Issue**: Models contain numpy arrays instead of trained models
- **Cause**: Model files were saved incorrectly (feature names saved instead of model object)
- **Fix**: Re-run training script: `python scripts/train_models.py`
- **Prevention**: Always use the training script, never manually save feature names

**Issue**: Insufficient data for training
- **Cause**: API returned fewer candles than expected
- **Fix**: Check Delta Exchange API connectivity and increase `limit` parameter

**Issue**: Feature computation fails
- **Cause**: Missing candles or invalid data
- **Fix**: Ensure candles have required fields (open, high, low, close, volume)

---

## Price Prediction Models

### Overview

The project includes a comprehensive price prediction training script (`scripts/train_price_prediction_models.py`) that supports both **regression** (price prediction) and **classification** (buy/sell/hold signal prediction) tasks using XGBoost and LSTM algorithms.

**Key Features**:
- **Pagination Support**: Automatically handles Delta Exchange API 2,000 candle limit
- **Data Reversal**: Converts API reverse chronological order to chronological order
- **Multiple Model Types**: XGBoost Regressor, XGBoost Classifier, LSTM Regressor, LSTM Classifier
- **Google Colab Optimized**: Designed for cloud training environments

### Regressor vs Classifier: Key Differences

**Regressor Models**:
- **Predict**: Absolute future prices (e.g., $50,500)
- **Training**: Uses future close prices as targets
- **Normalization**: Converts absolute price to relative return, then normalizes to [-1, 1]
- **Use Case**: Price prediction with magnitude information

**Classifier Models**:
- **Predict**: Trading signals directly (BUY/SELL/HOLD)
- **Training**: Uses return-based signal labels (BUY if return > 0.5%, SELL if return < -0.5%, HOLD otherwise)
- **Normalization**: Directly normalizes probabilities/class labels to [-1, 1]
- **Use Case**: Direct signal classification without price magnitude

**Consensus Calculation**: Both model types output normalized values in [-1, 1] range, allowing them to be combined in weighted consensus calculations.

## Current Model Support (2025-01-27)

### Supported Model Types

The system now supports **5 different ML model types** through the complete MCP Model Protocol implementation:

#### 1. XGBoost Models ✅ **FULLY IMPLEMENTED**
- **Classifiers**: Predict trading signals directly (buy/sell/hold) with `predict_proba()` method
- **Regressors**: Predict absolute future prices with `predict()` method
- **Auto-detection**: XGBoostNode automatically detects classifier vs regressor types
- **Normalization**: All outputs normalized to [-1, 1] range for consensus

#### 2. LightGBM Models ✅ **FULLY IMPLEMENTED**
- **Complete Implementation**: Full LightGBM Booster support with proper loading
- **SHAP Explanations**: Feature importance extraction for interpretability
- **Same Interface**: Compatible with MCP Model Protocol
- **Performance**: Alternative gradient boosting with potentially better speed

#### 3. Random Forest Models ✅ **FULLY IMPLEMENTED**
- **Scikit-learn Integration**: Full RandomForestClassifier/RandomForestRegressor support
- **Feature Importance**: Built-in feature importance extraction
- **Ensemble Method**: Bagging-based ensemble learning
- **Robust**: Good resistance to overfitting

#### 4. LSTM Models ✅ **FULLY IMPLEMENTED**
- **TensorFlow/Keras Support**: Complete neural network implementation
- **Sequence Processing**: Handles temporal dependencies in price data
- **Configurable Architecture**: Supports various LSTM configurations
- **GPU Acceleration**: Leverages TensorFlow's GPU capabilities

#### 5. Transformer Models ✅ **FULLY IMPLEMENTED**
- **Multi-format Support**: ONNX and PyTorch implementations
- **Attention Mechanisms**: Captures complex relationships in market data
- **Scalable Architecture**: Handles variable input sequences
- **Modern AI**: State-of-the-art transformer architectures

### Implementation Status

All model types are **production-ready** with:
- ✅ Complete MCP Model Node implementations
- ✅ Proper error handling and health monitoring
- ✅ SHAP explanations and feature importance
- ✅ Confidence scoring and normalization
- ✅ Parallel inference support
- ✅ Comprehensive validation

### Delta Exchange API Limitations

The training script properly handles Delta Exchange API constraints:

1. **2,000 Candle Limit**: Maximum candles per request is 2,000
   - Script automatically implements pagination for datasets > 2,000 candles
   - Calculates batches: `ceil(total_candles / 2000)`
   - Makes multiple requests with adjusted time ranges

2. **Reverse Chronological Order**: API returns data in reverse chronological order (newest first)
   - Script automatically reverses data to chronological order (oldest first)
   - Critical for time-series models (LSTM) which require chronological sequences

3. **Supported Resolutions**:
   - Valid: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `1d`, `1w`
   - Deprecated (do not use): `7d`, `2w`, `30d`

4. **Rate Limiting**: Script includes automatic rate limiting (0.75s delay between requests)

### Training Script Usage

#### Basic Usage

```bash
# Train regression and classification models for multiple timeframes
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m 1h 4h \
  --total-candles 5000
```

#### Advanced Options

```bash
# Train only regression models
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --regression \
  --no-classification

# Train with LSTM models (requires TensorFlow)
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --lstm

# Train only classification models
python scripts/train_price_prediction_models.py \
  --symbol BTCUSD \
  --timeframes 15m \
  --total-candles 5000 \
  --classification \
  --no-regression
```

### Model Types

#### 1. XGBoost Regressor

**Purpose**: Predict absolute future price (continuous value)

**Training Target**: Future close price (e.g., if current price is $50,000, predicts $50,500)

**Raw Output**: Absolute price value (e.g., 50500.0)

**Normalization**: The agent automatically converts regressor outputs to relative returns:
1. Calculates return percentage: `(predicted_price - current_price) / current_price`
2. Normalizes return to [-1, 1] range: ±10% return maps to ±1.0
3. Returns beyond ±10% are clamped to ±1.0

**Example**: 
- Current price: $50,000
- Predicted price: $50,500
- Return: +1.0%
- Normalized output: +0.1 (in [-1, 1] range)

**Usage**:
```python
import pickle
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/xgboost/xgboost_regressor_BTCUSD_15m.pkl")
with open(model_path, "rb") as f:
    model = pickle.load(f)

# Predict
features = np.array([[...]])  # 50 features
predicted_price = model.predict(features)  # Absolute price value
```

**Note**: When used in the agent, regressor predictions are automatically normalized to [-1, 1] range using current price from context. If current price is not available, a fallback normalization is used.

#### 2. XGBoost Classifier

**Purpose**: Predict trading signal directly (buy/sell/hold)

**Training Target**: Trading signals based on return thresholds:
- `1` (BUY) if return > 0.5%
- `-1` (SELL) if return < -0.5%
- `0` (HOLD) otherwise

**Raw Output**: Class probabilities or class labels

**Normalization**: Classifier outputs are normalized to [-1, 1] range:
- Probability output [0, 1] → [-1, 1]: `(probability - 0.5) * 2.0`
- Class label (0 or 1) → [-1, 1]: `(label * 2.0) - 1.0`

**Usage**:
```python
import pickle
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/xgboost/xgboost_classifier_BTCUSD_15m.pkl")
with open(model_path, "rb") as f:
    model = pickle.load(f)

# Predict
features = np.array([[...]])  # 50 features
signal = model.predict(features)  # 0, 1, or 2 (or -1, 0, 1 depending on training)
probabilities = model.predict_proba(features)  # [P(SELL), P(HOLD), P(BUY)] or [P(0), P(1)]
```

**Note**: Classifier models directly predict trading signals, so their outputs are more directly interpretable as buy/sell/hold decisions compared to regressors.

#### 3. LSTM Regressor

**Purpose**: Sequence-based price prediction (requires TensorFlow)

**Output**: Future price value

**Usage**:
```python
from tensorflow import keras
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/lstm/lstm_regressor_BTCUSD_15m.h5")
model = keras.models.load_model(model_path)

# Predict (requires sequence of 60 candles)
# Shape: (1, 60, N) - (batch, sequence_length, features); N depends on how the model was trained
sequence = np.array([[[...]]])  # 60 candles × N features
predicted_price = model.predict(sequence)
```

#### 4. LSTM Classifier

**Purpose**: Sequence-based signal prediction (requires TensorFlow)

**Output**: Class probabilities

**Usage**:
```python
from tensorflow import keras
import numpy as np
from pathlib import Path

# Load model
model_path = Path("agent/model_storage/lstm/lstm_classifier_BTCUSD_15m.h5")
model = keras.models.load_model(model_path)

# Predict (requires sequence of 60 candles)
sequence = np.array([[[...]]])  # 60 candles × N features
probabilities = model.predict(sequence)  # [P(SELL), P(HOLD), P(BUY)]
```

### Google Colab Training

- **v15 pipeline (5m / 15m)**: archival — full sklearn/XGBoost pipeline export, 20 features per TF, `metadata_*.json` + `pipeline_*_v14.pkl` (see family **A**).
- **Expanded v5 / v6 bundles**: archival — Delta API pagination, `UnifiedFeatureEngine`, metadata + joblib per timeframe (see family **B**).

See [Training Authority and Train-Serve Parity](#training-authority-and-train-serve-parity) and [Training, parity, and promotion](#training-parity-and-promotion).

Delta REST limits (e.g. **2,000 candles per request**), reverse-chronological candle order, and rate limits are handled inside those notebook workflows—mirror the same patterns if you add new training scripts.

### Training Output

Models are saved to the `agent/model_storage/` directory, organized by model type:

```
agent/model_storage/
├── xgboost/
│   ├── xgboost_regressor_BTCUSD_15m.pkl
│   ├── xgboost_classifier_BTCUSD_15m.pkl
│   ├── xgboost_regressor_BTCUSD_1h.pkl
│   ├── xgboost_classifier_BTCUSD_1h.pkl
│   └── ...
├── lstm/                              # If TensorFlow available
│   ├── lstm_regressor_BTCUSD_15m.h5
│   ├── lstm_classifier_BTCUSD_15m.h5
│   └── ...
└── price_prediction_training_summary.csv
```

Training metrics are saved to `agent/model_storage/price_prediction_training_summary.csv` with columns:
- `timeframe`: Timeframe identifier
- `model_type`: Model type (xgboost_regressor, xgboost_classifier, etc.)
- `train_metric`: Training metric (RMSE for regression, accuracy for classification)
- `val_metric`: Validation metric
- `test_metric`: Test metric
- `training_time`: Training time in seconds
- `model_path`: Path to saved model file

### Best Practices

1. **Start with Small Datasets**: Test with 3,000 candles before training on larger datasets
2. **Monitor API Usage**: Be aware of API rate limits when fetching large datasets
3. **Validate Models**: Always validate saved models before deployment
4. **Use Appropriate Timeframes**: Match training timeframe to trading strategy
5. **Consider LSTM for Sequences**: LSTM models capture temporal dependencies better than XGBoost

---

## Model Directory Structure

### Directory Layout

```
trading-agent/
├── agent/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── mcp_model_node.py          # Base MCP model interface
│   │   ├── mcp_model_registry.py      # Model registry
│   │   ├── model_discovery.py         # Automatic model discovery
│   │   └── xgboost_node.py            # Legacy generic node (retained for compatibility)
│   │
│   └── model_storage/                  # Uploaded model files
│       ├── xgboost/
│       │   ├── xgboost_v1.0.0.pkl
│       │   ├── xgboost_v1.1.0.pkl
│       │   └── metadata.json
│       ├── lstm/
│       │   ├── lstm_v1.0.0.h5
│       │   └── metadata.json
│       ├── transformer/
│       │   ├── transformer_v1.0.0.onnx
│       │   └── metadata.json
│       └── custom/                     # User-uploaded models
│           ├── my_custom_model.pkl
│           └── metadata.json
```

### Environment Configuration

Model storage is configured via environment variables in the root `.env` file:

```bash
# Points to directory for automatic model discovery
MODEL_DIR=./agent/model_storage
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
MIN_CONFIDENCE_THRESHOLD=0.65
```

**Important**: 
- `MODEL_DIR` is used by the model discovery system to find and register models from `agent/model_storage/` and its subdirectories
- All models are automatically discovered and registered on agent startup
- Models are organized by type in subdirectories (e.g., `xgboost/`, `lstm/`, `transformer/`)

---

## Model Upload Process

### Supported Model Formats

The system supports multiple model formats:

1. **Pickle (.pkl)** - Scikit-learn, XGBoost, LightGBM models
2. **H5/Keras (.h5, .keras)** - TensorFlow/Keras models
3. **ONNX (.onnx)** - ONNX Runtime models
4. **Joblib (.joblib)** - Scikit-learn models
5. **JSON (.json)** - Model weights and architecture

### Upload Directory

Models should be uploaded to the `agent/model_storage/custom/` directory:

```bash
# Create custom models directory if it doesn't exist
mkdir -p agent/model_storage/custom

# Copy your model file
cp my_model.pkl agent/model_storage/custom/

# Create metadata file (optional but recommended)
cat > agent/model_storage/custom/metadata.json << EOF
{
  "model_name": "my_custom_model",
  "model_type": "xgboost",
  "version": "1.0.0",
  "description": "Custom XGBoost model for BTCUSD",
  "features_required": ["rsi_14", "macd_signal", "volume_ratio"],
  "created_at": "2025-01-12T10:00:00Z"
}
EOF
```

### Model Metadata

Each model should have a `metadata.json` file with the following structure:

```json
{
  "model_name": "model_identifier",
  "model_type": "xgboost|lstm|transformer|lightgbm|custom",
  "version": "1.0.0",
  "description": "Model description",
  "author": "Author name",
  "created_at": "2025-01-12T10:00:00Z",
  "features_required": [
    "feature_name_1",
    "feature_name_2"
  ],
  "input_shape": [100, 20],
  "output_type": "regression|classification",
  "target": "price_change|signal",
  "training_data": {
    "period": "2024-01-01 to 2024-12-31",
    "symbol": "BTCUSD"
  },
  "performance_metrics": {
    "accuracy": 0.75,
    "sharpe_ratio": 1.5
  }
}
```

### Quick Upload Example

For repeatable deployments, use the helper script provided under `scripts/`:

```bash
python scripts/install_model.py \
  --source-path ./artefacts/xgboost_BTCUSD_1h.pkl \
  --dest-name xgboost_BTCUSD_1h_prod.pkl \
  --metadata ./artefacts/xgboost_BTCUSD_1h.metadata.json
```

The script performs checksum validation, copies the artefact into `agent/model_storage/custom/`, and updates the registry cache. Review the generated log output in `logs/scripts/install_model.log` to confirm the transfer succeeded.

---

## Model Discovery and Registration

### Automatic Discovery

The system automatically discovers models on startup:

```python
# agent/models/model_discovery.py
class ModelDiscovery:
    """Automatic model discovery and registration."""
    
    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.registry = MCPModelRegistry()
    
    def discover_and_register(self):
        """Discover all models and register them."""
        # Scan model directories
        model_files = self._scan_model_files()
        
        for model_file in model_files:
            try:
                # Detect model type
                model_type = self._detect_model_type(model_file)
                
                # Load metadata
                metadata = self._load_metadata(model_file)
                
                # Create model node
                model_node = self._create_model_node(
                    model_type, 
                    model_file, 
                    metadata
                )
                
                # Register with registry
                self.registry.register_model(model_node, metadata)
                
                logger.info(
                    f"Registered model: {metadata['model_name']} "
                    f"v{metadata['version']} ({model_type})"
                )
            except Exception as e:
                logger.error(f"Failed to register model {model_file}: {e}")
```

### Model Type Detection

The system intelligently detects model types:

```python
def _detect_model_type(self, model_file: Path) -> str:
    """Detect model type from file."""
    # Check file extension
    ext = model_file.suffix.lower()
    
    if ext == '.pkl':
        return self._detect_pickle_model_type(model_file)
    elif ext in ['.h5', '.keras']:
        return 'tensorflow'
    elif ext == '.onnx':
        return 'onnx'
    elif ext == '.joblib':
        return 'scikit-learn'
    else:
        # Try to infer from metadata
        metadata = self._load_metadata(model_file)
        return metadata.get('model_type', 'custom')
```

---

## AI Agent Model Intelligence

### Model Understanding

The AI agent intelligently understands and interacts with ML models:

#### 1. Model Capability Analysis

The agent analyzes each model's capabilities:

```python
class ModelIntelligence:
    """AI agent intelligence for model interaction."""
    
    def analyze_model_capabilities(self, model: MCPModelNode) -> Dict:
        """Analyze what a model can do."""
        model_info = model.get_model_info()
        
        return {
            "model_type": model_info['type'],
            "input_features": model_info['features_required'],
            "output_type": model_info['output_type'],
            "strengths": self._identify_strengths(model_info),
            "limitations": self._identify_limitations(model_info),
            "best_use_cases": self._identify_use_cases(model_info)
        }
    
    def _identify_strengths(self, model_info: Dict) -> List[str]:
        """Identify model strengths."""
        strengths = []
        
        model_type = model_info['type']
        if model_type == 'xgboost':
            strengths.extend([
                "Fast inference",
                "Good for non-linear patterns",
                "Feature importance available"
            ])
        elif model_type == 'lstm':
            strengths.extend([
                "Captures temporal dependencies",
                "Good for sequence patterns",
                "Handles variable-length sequences"
            ])
        elif model_type == 'transformer':
            strengths.extend([
                "Long-range dependencies",
                "Attention mechanisms",
                "Complex pattern recognition"
            ])
        
        return strengths
```

#### 2. Model Reasoning Integration

The agent reasons about which models to use and how to combine them:

```python
def reason_with_models(
    self,
    market_context: Dict,
    available_models: List[MCPModelNode]
) -> Dict:
    """Reason about which models to use and how."""
    
    # Analyze market context
    market_regime = market_context['regime']
    volatility = market_context['volatility']
    
    # Select appropriate models
    selected_models = []
    
    for model in available_models:
        model_capabilities = self.analyze_model_capabilities(model)
        
        # Reason about model suitability
        if self._is_model_suitable(model_capabilities, market_context):
            selected_models.append(model)
    
    # Determine model weights based on context
    model_weights = self._calculate_contextual_weights(
        selected_models,
        market_context
    )
    
    return {
        "selected_models": selected_models,
        "model_weights": model_weights,
        "reasoning": self._generate_reasoning_explanation(
            selected_models,
            market_context
        )
    }
```

#### 3. Model Type Understanding

The agent understands different model types and their characteristics:

**XGBoost Models**:
- Best for: Trend identification, feature-based patterns
- Strengths: Fast, interpretable, handles non-linear relationships
- Use when: Need quick predictions, want feature importance

**LSTM Models**:
- Best for: Sequence patterns, temporal dependencies
- Strengths: Captures time-series patterns, handles sequences
- Use when: Market shows clear temporal patterns

**Transformer Models**:
- Best for: Complex relationships, long-term dependencies
- Strengths: Attention mechanisms, captures complex patterns
- Use when: Need to understand complex market relationships

**LightGBM Models**:
- Best for: Fast gradient boosting, large feature sets
- Strengths: Efficient, good for many features
- Use when: Have many features, need speed

### Model Reasoning Example

```python
# Example: Agent reasoning about models
market_context = {
    "regime": "bull_trending",
    "volatility": "normal",
    "time_horizon": "short_term"
}

reasoning = agent.reason_with_models(market_context, available_models)

# Output:
# {
#   "selected_models": [xgboost_model, lstm_model],
#   "model_weights": {
#     "xgboost": 0.6,
#     "lstm": 0.4
#   },
#   "reasoning": "For bull trending market with normal volatility, 
#                 XGBoost excels at trend identification (60% weight),
#                 while LSTM captures sequence patterns (40% weight)"
# }
```

---

## Model Versioning and Management

### Version Management

Models are versioned using semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes, incompatible with previous versions
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

### Version Tracking

```python
class ModelVersionManager:
    """Manage model versions."""
    
    def register_version(
        self,
        model_name: str,
        version: str,
        model_file: Path,
        metadata: Dict
    ):
        """Register a new model version."""
        version_info = {
            "version": version,
            "file_path": str(model_file),
            "metadata": metadata,
            "registered_at": datetime.utcnow(),
            "is_active": True
        }
        
        self.versions[model_name].append(version_info)
    
    def get_latest_version(self, model_name: str) -> str:
        """Get latest version of a model."""
        versions = self.versions.get(model_name, [])
        if not versions:
            return None
        
        # Sort by version
        sorted_versions = sorted(
            versions,
            key=lambda v: self._parse_version(v['version']),
            reverse=True
        )
        
        return sorted_versions[0]['version']
```

### Model Lifecycle

1. **Upload**: Model file placed in `model_storage/custom/`
2. **Discovery**: System discovers model on next startup
3. **Registration**: Model registered with MCP Model Registry
4. **Validation**: Model validated for compatibility
5. **Activation**: Model activated for use in predictions
6. **Monitoring**: Model performance monitored
7. **Retirement**: Old versions retired when new versions available

---

## Custom Model Integration

### Creating Custom Model Nodes

To integrate a custom model, create a model node class:

```python
# agent/models/custom_model_node.py
from agent.models.mcp_model_node import MCPModelNode
from agent.models.mcp_model_protocol import MCPModelRequest, MCPModelPrediction

class CustomModelNode(MCPModelNode):
    """Custom model node implementation."""
    
    def __init__(self, model_path: str, metadata: Dict):
        self.model_name = metadata['model_name']
        self.model_version = metadata['version']
        self.model_type = metadata['model_type']
        self.model_path = model_path
        self.metadata = metadata
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load model from file."""
        import pickle
        
        with open(self.model_path, 'rb') as f:
            self.model = pickle.load(f)
    
    async def predict(
        self, 
        request: MCPModelRequest
    ) -> MCPModelPrediction:
        """Generate prediction."""
        # Extract features
        features = self._extract_features(request.features)
        
        # Generate prediction
        prediction_value = self.model.predict(features)
        
        # Normalize to -1.0 to +1.0 range
        normalized_prediction = self._normalize_prediction(prediction_value)
        
        # Generate SHAP explanation
        shap_values = self._calculate_shap_values(features)
        reasoning = self._generate_shap_reasoning(shap_values, features)
        feature_importance = self._extract_feature_importance(shap_values, features)
        
        return MCPModelPrediction(
            model_name=self.model_name,
            model_version=self.model_version,
            prediction=normalized_prediction,
            confidence=self._calculate_confidence(features),
            reasoning=reasoning,
            features_used=[f.name for f in request.features],
            feature_importance=feature_importance,
            computation_time_ms=self._measure_computation_time(),
            health_status="healthy"
        )
    
    def _calculate_shap_values(self, features):
        """Calculate SHAP values for explanation."""
        import shap
        explainer = shap.TreeExplainer(self.model)  # For tree-based models
        shap_values = explainer.shap_values(features)
        return shap_values
    
    def _generate_shap_reasoning(self, shap_values, features):
        """Generate human-readable reasoning from SHAP values."""
        # Get top contributing features
        feature_names = [f.name for f in features]
        contributions = dict(zip(feature_names, shap_values))
        top_features = sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
        
        # Generate explanation
        reasoning_parts = []
        for feature_name, contribution in top_features:
            direction = "supports" if contribution > 0 else "opposes"
            reasoning_parts.append(f"{feature_name} ({contribution:+.3f}) {direction} the prediction")
        
        return f"Model prediction based on: {', '.join(reasoning_parts)}"
    
    def _extract_feature_importance(self, shap_values, features):
        """Extract feature importance from SHAP values."""
        feature_names = [f.name for f in features]
        return dict(zip(feature_names, shap_values))
    
    def get_model_info(self) -> Dict:
        """Get model information."""
        return {
            "type": self.model_type,
            "features_required": self.metadata.get('features_required', []),
            "output_type": self.metadata.get('output_type', 'regression'),
            "capabilities": self.metadata.get('capabilities', [])
        }
```

### Model Requirements

Custom models must:

1. **Implement MCPModelNode interface**
2. **Return predictions in -1.0 to +1.0 range**
3. **Provide reasoning/explanations**
4. **Include metadata.json file**
5. **Support feature extraction from MCPFeature objects**

---

## Model Performance Tracking

### Performance Metrics (implementation: agent/core/learning_system.py)

The `ModelPerformanceTracker` tracks **trade outcomes** (per-model PnL and win/loss), not raw prediction-vs-outcome error. This avoids using a continuous error metric (e.g. MAE) for classifier predictions, which would mix normalized signal [-1, 1] with actual return and mis-rank models.

**Implemented API:**
- `record_trade_outcome(trade_outcome: TradeOutcome, model_predictions: List[Dict])` — records a closed trade for each participating model; triggered from the state machine on `PositionClosedEvent` when `model_predictions` are present in the payload.
- Metrics maintained per model: `total_trades`, `profitable_trades`, `total_pnl`, `win_rate`, `avg_pnl`, `sharpe_ratio` (from recent returns), `recent_performance` (last 50 trades).
- `get_model_weight(model_name, base_weight)` — returns a dynamic weight from win rate, Sharpe, and recent performance (used when learning is enabled).

**If adding prediction-level outcome recording:** For classifiers, use directional accuracy (e.g. `sign(prediction) == sign(actual_return)`) or a classification metric (e.g. AUC), not `abs(prediction - actual_outcome)`, so correct direction is rewarded regardless of magnitude.

---

## Model Inference Testing

### Automated Smoke Test

Use `scripts/test_model_inference.py` to validate that every model stored under `agent/model_storage/` can be discovered, loaded, and queried end-to-end without starting the full agent:

```bash
python scripts/test_model_inference.py \
  --model-dir agent/model_storage
```

The script runs the standard discovery pipeline, issues a lightweight prediction request to each registered node, and prints a confidence summary so regressions are obvious in CI logs. It also reports which artefacts failed to deserialize so you can remove or regenerate them before production deployments.

### Latest Validation Snapshot

Running the script against models in `agent/model_storage/` validates that all models can be discovered, loaded, and queried. The script reports which models load successfully and which fail to deserialize.

Keep this section updated whenever the script uncovers model-health changes so other contributors know which artefacts require attention.

### Feature Vector Expectations

The MCP orchestrator now forwards both the ordered feature values and the associated `feature_names` inside the model request context. Models must continue to:

1. Accept a `List[float]` feature vector shaped exactly like their training data.
2. Read `request.context["feature_names"]` when feature importance needs human-readable labels.
3. Validate the feature count and raise a descriptive error if the input is malformed.

Document the expected feature order inside each model’s metadata so downstream scripts (including the inference smoke test) can source realistic inputs.

---

## Best Practices

### Model Upload

1. **Use semantic versioning** for model versions
2. **Include complete metadata.json** with all required fields
3. **Test model locally** before uploading
4. **Document model capabilities** in metadata
5. **Specify required features** clearly

### Model Development

1. **Follow MCP Model Protocol** for consistency
2. **Normalize predictions** to -1.0 to +1.0 range
3. **Provide meaningful explanations** for predictions
4. **Handle missing features** gracefully
5. **Log model operations** for debugging

### Model Management

1. **Keep old versions** for rollback capability
2. **Monitor model performance** regularly
3. **Retire underperforming models** gracefully
4. **Document model changes** in metadata
5. **Test new versions** before activation

---

## Troubleshooting

### Model Not Discovered

**Problem**: Model not appearing in registry

**Solutions**:
1. Check model file is in correct directory (`model_storage/custom/`)
2. Verify metadata.json exists and is valid JSON
3. Check model file permissions
4. Review agent logs for discovery errors
5. Ensure `MODEL_DISCOVERY_ENABLED=true` in `.env`

### Model Loading Errors

**Problem**: Model fails to load

**Solutions**:
1. Verify model file format is supported
2. Check model dependencies are installed
3. Verify model file is not corrupted
4. Check model compatibility with Python version (re-export pickled models using `Booster.save_model()` or the framework-native exporter before upgrading XGBoost/LightGBM versions)
5. Review error logs for specific issues
6. If you observe `invalid load key` errors, delete the affected file from `agent/model_storage/` and replace it with a freshly serialized artefact from the training environment.

### Model Prediction Errors

**Problem**: Model predictions fail

**Solutions**:
1. Verify required features are available
2. Check feature format matches model expectations (the context now carries both `features` and `feature_names`; custom nodes should rely on those keys instead of positional assumptions)
3. Verify model is properly loaded
4. Check model health status
5. Review prediction logs for errors

### Metadata Mismatch

**Problem**: Registry logs show `metadata_validation_failed` and the model remains inactive.

**Solutions**:
1. Ensure the metadata schema includes all mandatory fields listed in [Model Metadata](#model-metadata) (name, type, version, features, training data block).
2. Confirm the version string matches semantic versioning (`MAJOR.MINOR.PATCH`). Values like `"1.0"` will be rejected.
3. Check that `features_required` lines up with the actual feature names emitted by the MCP Feature Server. Typos cause the registry to reject the model.
4. Run `python scripts/validate_metadata.py --path agent/model_storage/custom/metadata.json` to lint the file locally before restarting the agent.
5. Inspect the agent logs for the detailed validation error payload and adjust the metadata accordingly.

---

## Bundle profiles and Docker defaults

Common bundle layouts; always point **`MODEL_DIR` / `AGENT_MODEL_DIR`** at the folder you intend to run.

| Profile | Typical path | Contents |
|--------|--------------|----------|
| **IC (Compose default — NO-ML)** | `agent/model_storage/JackSparrow_IC_BTCUSD/` | **`metadata_ic.json`** only; **`RuleBasedIntelligenceNode`**; v43 feature contract + gates at runtime. |
| **v43 regression (archived)** | `agent/model_storage/JackSparrow_v43_models_BTCUSD/` | **`metadata_v43.json`** + pickles; not loaded by current discovery. |
| **Historical v15 pipeline** | `agent/model_storage/jacksparrow_v15_BTCUSD_<date>/` | **5m + 15m** subfolders: `metadata_BTCUSD_*.json` + `pipeline_*_v14.pkl`; used for parquet **adaptive retrain** tooling and archived validation—not primary discovery in this branch. |
| **Historical full multi-TF v5** | `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19/` | Five horizons (15m–4h) with entry + exit joblib per timeframe (when exported). |
| **Historical slim v5** | `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21/` | Often **5m + 15m** metadata; binary long/short entry heads; **no ML exit** in metadata by default—see each `metadata_*.json` `artifacts` and `exit_policy_note`. |

Override **`AGENT_MODEL_DIR`** when you duplicate the IC bundle folder under a different name (see **[Deployment — Agent Environment Variables](10-deployment.md#agent-environment-variables)**).

## Inference MCP flow (runtime)

1. `MCPOrchestrator.initialize()` creates `MCPFeatureServer`, `MCPModelRegistry`, and `MCPReasoningEngine`.
2. `ModelDiscovery.discover_models()` loads **`MODEL_DIR/metadata_ic.json`**, instantiates **`RuleBasedIntelligenceNode`**, and registers it when `IC_MODE=true` and `MODEL_AUTO_REGISTER=true`.
3. On each closed bar, the orchestrator requests features (v43 MCP row path), runs **`RuleBasedIntelligenceNode.predict`**, applies **`v43_signal_gates`**, and merges **`expected_return`**, **`regime`**, gate fields, and **`desired_side`** into market context for policy and reasoning.
4. WebSocket payloads to the frontend are enriched in **`backend/services/agent_event_subscriber.py`** (**`expected_return`**, **`mcp_tanh_prediction`**, **`v43_gate_reject`**) and persisted under Redis key **`jacksparrow:v43:signal_history:<symbol>`** for recent-tail diagnostics.

### Historical multi-node flow (forks only)

Older branches scanned **`metadata_BTCUSD_*.json`** and registered **`PipelineV15Node`** or **`V4EnsembleNode`** per timeframe. Restore that scanner in `agent/models/model_discovery.py` if you deliberately run those bundles again.

**Entry vs exit at execution**: ML output is packaged as **evidence** (`EVIDENCE_READY`); the **AgentPolicyEngine** emits `DECISION_READY` with `policy_authority=agent_policy` before the trading handler and risk manager. **`exit_signal`** semantics from ensemble-era nodes do not apply verbatim to **`JackSparrowV43Node`**. Position closes follow risk rules—see [Logic & Reasoning](05-logic-reasoning.md#entry-vs-exit-signals-and-position-closes).

## Training, parity, and promotion

- **v43 bundle (Compose default)** — **`notebooks/jacksparrow_v43_delta_india_training.ipynb`** → promote per [Operational Workflow (bundle-first)](#operational-workflow-bundle-first): copy export, run **`scripts/patch_v43_model_artifact.py`**, verify Pattern 3 metadata gates, restart agent. **Smoke**: **`python scripts/smoke_test_v43.py`**; **Tests**: **`pytest tests/unit/test_jacksparrow_v43_contract.py ...`**; **Operational**: **`docs/jacksparrow_v43_smoke.md`** and **`docs/v43_trade_execution_runbook.md`**.
- **Historical v15 pipeline**: archival notebook removed; after export, `metadata_*.json` `features` must match `V15_FEATURES_5M` / `V15_FEATURES_15M` in `feature_store/feature_registry.py` (names and order). **Checks**: `pytest tests/unit/test_v15_feature_registry.py -q`, `pytest tests/unit/test_feature_parity.py -q`, `python scripts/test_model_inference.py --model-dir <bundle_path>` when available, `python scripts/validate_models_before_deployment.py <bundle_root>`.
- **Historical v5 / v6 expanded bundles**: archival notebooks removed (UnifiedFeatureEngine, `EXPANDED_FEATURE_LIST` / `feature_store/feature_registry.py`, fee-aware TP/SL labeling, metadata + joblib per timeframe).
- **Learning DB**: apply `prediction_audit` / `trade_outcomes` migrations (`scripts/migrate_model_governance.py`) when using learning features.

### Single-model (consolidated) mode (historical)

When using a consolidated export from the v5 notebook on a branch that still supports this flow:

```bash
SINGLE_MODEL_MODE_ENABLED=true
MODEL_DIR=./agent/model_storage/jacksparrow_v5_BTCUSD_YYYY-MM-DD
CONSOLIDATED_MODEL_METADATA_GLOB=metadata_BTCUSD_consolidated*.json
USE_ML_EXIT_MODEL=false
```

### JackSparrow v15 pipeline (5m / 15m joblib) — historical

This was the **full-pipeline** artefact path (one XGBoost/sklearn pipeline per timeframe, three-class `predict_proba`, edge = `p_buy − p_sell`). **Current `model_discovery.py` no longer loads v15 nodes**; keep this section for adaptive retrain assets and manual validation.

- **Bundle layout**: `agent/model_storage/jacksparrow_v15_BTCUSD_2026-04-05/{5m,15m}/` with `metadata_BTCUSD_*.json` and `pipeline_*_v14.pkl`. You can also keep the older flat `model_5m_v14/` style if discovery resolves the pickle path next to metadata (see `metadata_is_v15_pipeline()` in `agent/models/pipeline_v15_node.py`).
- **Pickle shape**: Exports may be a bare estimator or a **`dict` with a `model` key** (Colab bundle). `PipelineV15Node` unwraps `dict["model"]` before `predict_proba`.
- **`MODEL_FORMAT`**: Defaults to **`jacksparrow_v43`** for health display; v15-specific toggles in [`agent/core/config.py`](../agent/core/config.py) are **deprecated for primary inference** (see `.env.example`).
- **Code map**: `agent/models/pipeline_v15_node.py` (load/infer), `agent/models/mcp_model_registry.py` (health), `agent/core/mcp_orchestrator.py`, `agent/core/v15_signal.py` + `agent/events/handlers/trading_handler.py` (v15 entry gate; **skipped** when `AI_SIGNAL_MINIMAL_ENTRY_GATES=true` — see [Logic & reasoning](05-logic-reasoning.md#trading-handler-default-vs-minimal-ai-entry-gates)), `agent/core/execution.py` (ATR trail, `v15_min_hold_until`, `atr_trail_stop` exit reason when applicable).
- **Features**: Canonical name lists in `feature_store/feature_registry.py` (`V15_FEATURES_5M`, `V15_FEATURES_15M`, `V15_FEATURES_BY_TF`). Rows are built in `feature_store/v15_feature_compute.py`; the MCP path is selected in `agent/data/feature_server.py` when `candle_interval` matches a full v15 set. **5m** pulls **15m** OHLCV for `*_15m` columns; **15m** 15m candle cache uses Redis key `jacksparrow:v15:htf15:{symbol}` with `HTF_CACHE_TTL_SECONDS`.
- **Train–serve checklist**: After each Colab export, confirm the `features` array in each `metadata_BTCUSD_*.json` equals the corresponding `V15_FEATURES_*` list in the repo (update `feature_registry.py` first if you intentionally changed the training feature set). The shipped `pipeline_*_v14.pkl` was fit on those columns in that order; do not reorder metadata without retraining.
- **Environment** (see root `.env.example`, mostly commented for v15): `CONFIDENCE_PERCENTILE`, `EDGE_FLOOR`, `ATR_TRAILING_MULT`, `MIN_HOLD_BARS`, `EDGE_DECAY_THRESHOLD`, `VOLATILITY_FILTER_ENABLED`, `V15_ATR_PCT_FLOOR`, `V15_ADX_RANGING_MAX`, `V15_SIGNAL_LOGIC_ENABLED`, `V15_DISABLE_MTF_SYNTHESIS`, `V15_FILTER_FEATURE_SOURCE_TF`, `HTF_CACHE_TTL_SECONDS`.
- **Validation**: `python scripts/validate_models_before_deployment.py [<bundle_root>]` — loads metadata feature order + `predict_proba` shape `(1,3)`. **Tests**: `pytest tests/unit/test_v15_signal.py tests/unit/test_v15_feature_registry.py -q`. **Smoke** (backend up): `python scripts/smoke_test_v15.py`.
- **Rollback / promotion (archived v43)**: On a fork that still loads pickles, point **`MODEL_DIR`** at **`JackSparrow_v43_models_BTCUSD/`** and follow **`docs/jacksparrow_v43_smoke.md`**. On **NO-ML**, use **`JackSparrow_IC_BTCUSD/`** and IC unit tests instead.

## Runtime hardening (learning and reasoning)

- `MCPReasoningRequest.use_memory` is honored for Step-2 retrieval when a vector store exists.
- Threshold adaptation uses Redis `pipeline(transaction=True)` for atomic multi-key updates; retraining subprocess runs are serialized; retraining state uses atomic file replace where implemented.
- `TIMEFRAMES` config validation rejects non-string values (fail fast).

## Script hygiene

Prefer canonical scripts under `scripts/` and `tools/commands/`. Treat duplicate trees such as `scripts/files(3)/` as non-authoritative. Ad-hoc planning copies under `files(4)/` were **removed**; v15 integration detail lives in this file and in `05-logic-reasoning.md`, `04-features.md`, `06-backend.md`, and `07-frontend.md`.

---

## Related Documentation

- [MCP Layer Documentation](02-mcp-layer.md) - MCP protocol details
- [Architecture Documentation](01-architecture.md) - System architecture
- [Logic & Reasoning Documentation](05-logic-reasoning.md) - Reasoning engine
- [Deployment Documentation](10-deployment.md) - Setup instructions
- [Build Guide](11-build-guide.md) - Build instructions

