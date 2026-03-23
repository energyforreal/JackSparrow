# Model Integration Summary (v5 BTCUSD)

> **Canonical numbered guides**: Prefer [ML Models](03-ml-models.md) for ongoing edits; this page summarizes bundles and discovery.

> **Two bundle profiles:** the repo may contain both a **full five-timeframe** export and a **slim Docker default** export. Always match `MODEL_DIR` / `AGENT_MODEL_DIR` to the folder you intend to run.

## Overview

Runtime inference uses **metadata-driven discovery**: each `metadata_BTCUSD_*.json` under `MODEL_DIR` loads a **`V4EnsembleNode`** (the loader name is historical; bundles may be v5). Feature count is defined per metadata (`features_required` / `n_features`), not a single fixed “122” number — e.g. the **2026-03-21** slim bundle uses **~126** expanded features.

### Bundle A — Full multi-timeframe (2026-03-19)

- Path: `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-19/`
- Five horizons (15m–4h) with **entry + exit** joblib artefacts per timeframe (see files on disk).

### Bundle B — Docker default slim export (2026-03-21)

- Path: `agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21/`
- Typically **5m + 15m** metadata; **binary long/short** entry heads; **no ML exit joblib** in metadata (see each `metadata_*.json` `artifacts` and `exit_policy_note`).
- **Docker Compose** defaults `MODEL_DIR` to this folder via `AGENT_MODEL_DIR`.

Override `AGENT_MODEL_DIR` in root `.env` when promoting a different dated folder. See [ML Models in Docker](03-ml-models.md#ml-models-in-docker).

## Integrated Models

**If using bundle A (2026-03-19):** five timeframe nodes (15m, 30m, 1h, 2h, 4h) with entry/exit artefacts as exported.

**If using bundle B (2026-03-21):** two timeframes (5m, 15m) unless you add more metadata files to that folder.

## Discovery Contract

```bash
# Example: slim Docker bundle (matches default compose)
MODEL_DIR=./agent/model_storage/jacksparrow_v5_BTCUSD_2026-03-21
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
# Recursive scan of subfolders under MODEL_DIR (default true)
# MODEL_DISCOVERY_RECURSIVE=true
```

Discovery behaviour:

- With **`MODEL_DISCOVERY_RECURSIVE=true`** (default), `ModelDiscovery` uses `rglob("metadata_BTCUSD_*.json")` under `MODEL_DIR`.
- With **`MODEL_DISCOVERY_RECURSIVE=false`**, only the top-level `MODEL_DIR` directory is scanned.
- Each metadata file is loaded via `V4EnsembleNode.from_metadata(...)`.

## MCP Flow

1. `MCPOrchestrator.initialize()` creates `MCPModelRegistry`.
2. `ModelDiscovery.discover_models()` scans `MODEL_DIR` for `metadata_BTCUSD_*.json`.
3. Each metadata file loads a `V4EnsembleNode`.
4. Nodes are registered in `MCPModelRegistry`.
5. During inference, each node returns:
   - `prediction` (entry signal),
   - per-model `context` including `entry_signal` and `exit_signal`.

## Verification Checklist

1. Confirm metadata files exist for your chosen bundle directory.
2. Confirm discovery logs show non-zero registered models.
3. Confirm health payload reports non-zero `total_models` under the model registry component.
4. Run `tests/unit/test_feature_parity.py` after training or before promotion.
5. Ensure `prediction_audit` and `trade_outcomes` migrations have been applied (`scripts/migrate_model_governance.py`) when using learning features.

## Script hygiene

`scripts/files(3)/` is a duplicate/archive-style tree; prefer the canonical copies under `scripts/` for maintenance. See also `tools/commands/` for operational validators.
