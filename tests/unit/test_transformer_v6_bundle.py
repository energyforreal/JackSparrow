"""v6 bundle loading rejects older transformer contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.models.transformer_node import TransformerModelNode
from feature_store.transformer_btcusd.contract import (
    FEATURE_CONTRACT_VERSION,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    model_family_for_resolution,
    onnx_filename_for_resolution,
)
from feature_store.transformer_btcusd.inference import require_onnx_output_names


def test_from_metadata_path_rejects_v5_contract(tmp_path: Path) -> None:
    meta = {
        "model_name": "jacksparrow_transformer_BTCUSD_15m",
        "version": "transformer_per_tf_v1",
        "model_family": model_family_for_resolution("15m"),
        "resolution": "15m",
        "onnx_filename": onnx_filename_for_resolution("15m"),
    }
    cfg = {
        "feature_contract_version": "transformer_btcusd_per_tf_features_v5",
        "window_len": 128,
        "feature_cols": ["ret_1"],
    }
    (tmp_path / TRANSFORMER_METADATA_FILENAME).write_text(
        json.dumps(meta), encoding="utf-8"
    )
    (tmp_path / TRANSFORMER_FEATURE_CONFIG_FILENAME).write_text(
        json.dumps(cfg), encoding="utf-8"
    )
    (tmp_path / onnx_filename_for_resolution("15m")).write_bytes(b"not-onnx")
    with pytest.raises(RuntimeError, match=FEATURE_CONTRACT_VERSION):
        TransformerModelNode.from_metadata_path(tmp_path / TRANSFORMER_METADATA_FILENAME)


def test_v5_onnx_names_rejected() -> None:
    with pytest.raises(RuntimeError, match="missing outputs"):
        require_onnx_output_names(["continuous_pred", "regime_logits"])
