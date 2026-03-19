JackSparrow v4 BTCUSD Models
============================

This directory is the **project-managed home** for your trained BTCUSD v4 models.

Copy or sync the contents of your local models directory:

- Source (on host): `C:\Users\lohit\Downloads\jacksparrow_models_v4_BTCUSD`
- Target (inside repo): `agent/model_storage/jacksparrow_v4_BTCUSD`

When running under Docker, this folder is mounted into the agent container at:

- `/app/agent/model_storage/jacksparrow_v4_BTCUSD`

Model discovery configuration
-----------------------------

The v4 agent discovers BTCUSD models from the directory pointed to `MODEL_DIR`.

For v4, set:

- `MODEL_DIR=./agent/model_storage/jacksparrow_v4_BTCUSD` (see `.env.example` and `agent/.env.example`)

and ensure:

- `MODEL_DISCOVERY_ENABLED=true`
- `MODEL_AUTO_REGISTER=true`

The discovery service in v4-only mode:

- does **not** scan subdirectories under `MODEL_DIR`,
- looks for `metadata_BTCUSD_*.json` files directly in `MODEL_DIR`,
- loads each metadata file via `V4EnsembleNode.from_metadata(...)`,
- registers the resulting v4 entry/exit ensemble nodes with the MCP model registry.

After copying the v4 artifacts here and setting `MODEL_DIR` accordingly, restart the agent so the new models are loaded.
