"""Legacy 15m module tests — delegates to per-TF contract where applicable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.models.transformer_context_builder import build_transformer_prediction_context
from feature_store.transformer_btcusd_15m.contract import TRANSFORMER_MODEL_FAMILY


def test_build_transformer_prediction_context_per_tf() -> None:
    preds = {
        "future_return": 0.006,
        "future_volatility": 0.003,
        "mae": 0.008,
        "mfe": 0.02,
        "trend_strength": 1.6,
    }
    ctx, pred_val, conf = build_transformer_prediction_context(
        bundle_metadata={
            "resolution": "15m",
            "default_threshold": 0.005,
            "path_label_horizon_bars": 8,
        },
        continuous_preds=preds,
        vol_regime="NORMAL",
        regime_probs={"NORMAL": 1.0},
        bar_index_hint=50,
        resolution_minutes=15,
    )
    assert ctx["format"] == "jacksparrow_transformer_btcusd_per_tf"
    assert ctx["expected_return"] == pytest.approx(0.006)
    assert -1.0 <= pred_val <= 1.0
    assert 0.0 <= conf <= 1.0


def test_transformer_metadata_bundle_manifest(tmp_path: Path) -> None:
    bundle = Path("agent/model_storage/JackSparrow_Transformer_BTCUSD/metadata_transformer.json")
    if not bundle.is_file():
        pytest.skip("legacy bundle manifest not present")
    raw = json.loads(bundle.read_text(encoding="utf-8"))
    assert raw["model_family"] == TRANSFORMER_MODEL_FAMILY
