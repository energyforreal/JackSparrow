# Feature computation entrypoints (train / live / MCP)

Single source of truth for **generic** JackSparrow feature names used by legacy pipelines is [`feature_store/unified_feature_engine.py`](../feature_store/unified_feature_engine.py) (`UnifiedFeatureEngine`). Perpetual swap columns are derived only via `compute_perpetual_features` from [`feature_store/perpetual_features.py`](../feature_store/perpetual_features.py), which is **imported only** by `UnifiedFeatureEngine` (grep the repo to confirm).

## Delegation wrappers (all call `UnifiedFeatureEngine`)

| Module | Role |
|--------|------|
| [`feature_store/feature_pipeline.py`](../feature_store/feature_pipeline.py) | Batch `compute_features` / pipeline class |
| [`agent/data/feature_engineering.py`](../agent/data/feature_engineering.py) | Agent-side `FeatureEngineering` service |
| [`feature_store/v15_feature_compute.py`](../feature_store/v15_feature_compute.py) | v15-specific helpers; instantiates `UnifiedFeatureEngine` for shared OHLCV math |

## Live MCP feature server

[`agent/data/feature_server.py`](../agent/data/feature_server.py) uses `FeatureEngineering` (→ `UnifiedFeatureEngine`) for generic MCP feature rows. For **v43 named features** on HTTP/MCP paths without the pickled `feature_engineer`, it uses [`feature_store/jacksparrow_v43_mcp_row.py`](../feature_store/jacksparrow_v43_mcp_row.py) (`build_v43_last_row`), which is kept in lockstep with [`feature_store/jacksparrow_v43_contract.py`](../feature_store/jacksparrow_v43_contract.py) (`V43_CANONICAL_FEATURES`).

## JackSparrow v43 closed-bar inference (primary production path)

**Training notebook:** [`notebooks/jacksparrow_v43_delta_india_training.ipynb`](../notebooks/jacksparrow_v43_delta_india_training.ipynb) (Colab: clone branch **`major-rework`**). **Promotion:** copy export into `agent/model_storage/JackSparrow_v43_models_BTCUSD/`, run [`scripts/patch_v43_model_artifact.py`](../scripts/patch_v43_model_artifact.py) — see [ML models — Operational Workflow](../docs/03-ml-models.md#operational-workflow-bundle-first).

| Stage | Location |
|-------|----------|
| Canonical feature order / version gate | [`feature_store/jacksparrow_v43_contract.py`](../feature_store/jacksparrow_v43_contract.py) (`validate_v43_metadata_compatibility` at model load) |
| Full-bar matrix (shim / training alignment) | [`feature_store/jacksparrow_v43_build_matrix.py`](../feature_store/jacksparrow_v43_build_matrix.py) |
| MCP node; calls `feature_engineer.transform()` from artifact | [`agent/models/jack_sparrow_v43_node.py`](../agent/models/jack_sparrow_v43_node.py) — requires **`v43_df5m`** and **`v43_df_funding`** as `DataFrame`; **`v43_df15m`** / **`v43_df1h`** may be omitted or `None` (empty frames are substituted before `transform`). |

Training exports `feature_engineer.pkl` + `metadata_v*.json`; the agent must not reimplement that transform for the primary predict path—only the MCP row builder duplicates formulas where the server lacks the pickle.

## Tests and guardrails

- [`tests/unit/test_feature_parity.py`](../tests/unit/test_feature_parity.py) — `UnifiedFeatureEngine` vs metadata feature lists.
- [`tests/unit/test_jacksparrow_v43_contract.py`](../tests/unit/test_jacksparrow_v43_contract.py) — shipped metadata vs `V43_CANONICAL_FEATURES`.

## Out of scope / research only

- `notebooks/` and `_tmp_*.py` extracts may define alternate feature code; they must not be imported by the agent runtime. Training outputs should feed the paths above.

When adding a new model bundle, extend this document and the contract tests in the same change.
