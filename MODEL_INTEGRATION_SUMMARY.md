# Model Integration Summary (v4 BTCUSD)

## Overview

The project is integrated with **v4 BTCUSD entry/exit ensemble models** stored in:

- `agent/model_storage/jacksparrow_v4_BTCUSD/`

The runtime uses metadata-driven model discovery and registers one model node per
timeframe in the MCP model registry.

## Integrated Models

The current deployment includes five timeframe models:

- `jacksparrow_BTCUSD_15m`
- `jacksparrow_BTCUSD_30m`
- `jacksparrow_BTCUSD_1h`
- `jacksparrow_BTCUSD_2h`
- `jacksparrow_BTCUSD_4h`

Each timeframe is represented by:

- `metadata_BTCUSD_<tf>.json`
- `entry_model_BTCUSD_<tf>.joblib`
- `exit_model_BTCUSD_<tf>.joblib`
- `entry_scaler_BTCUSD_<tf>.joblib`
- `exit_scaler_BTCUSD_<tf>.joblib`
- `features_BTCUSD_<tf>.json`

## Discovery Contract

Use the following environment configuration:

```bash
MODEL_DIR=./agent/model_storage/jacksparrow_v4_BTCUSD
MODEL_DISCOVERY_ENABLED=true
MODEL_AUTO_REGISTER=true
```

In v4-only mode:

- discovery reads `metadata_BTCUSD_*.json` directly from `MODEL_DIR`,
- discovery is non-recursive,
- each metadata file is loaded via `V4EnsembleNode.from_metadata(...)`.

## MCP Flow

1. `MCPOrchestrator.initialize()` creates `MCPModelRegistry`.
2. `ModelDiscovery.discover_models()` scans `MODEL_DIR` for `metadata_BTCUSD_*.json`.
3. Each metadata file loads a `V4EnsembleNode`.
4. Nodes are registered in `MCPModelRegistry`.
5. During inference, each node returns:
   - `prediction` (entry signal),
   - per-model `context` including `entry_signal` and `exit_signal`.

## Verification Checklist

1. Confirm metadata files exist:
   - `agent/model_storage/jacksparrow_v4_BTCUSD/metadata_BTCUSD_*.json`
2. Confirm discovery logs show loaded v4 models.
3. Confirm health payload reports non-zero `model_registry.total_models`.
4. Confirm prediction payload contains:
   - `model_predictions[*].context.entry_signal`
   - `model_predictions[*].context.exit_signal`
