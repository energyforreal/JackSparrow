"""On-disk v15 bundle under agent/model_storage must match feature_registry and loader rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_store.feature_registry import V15_FEATURES_5M, V15_FEATURES_15M
from agent.models.pipeline_v15_node import metadata_is_v15_pipeline

BUNDLE = ROOT / "agent" / "model_storage" / "jacksparrow_v15_BTCUSD_2026-04-05"


@pytest.mark.skipif(not BUNDLE.is_dir(), reason="v15 bundle directory missing")
def test_jacksparrow_v15_bundle_layout_and_parity() -> None:
    """Metadata lists and pipeline filenames match PipelineV15Node + feature_registry."""
    metas = sorted(BUNDLE.rglob("metadata_BTCUSD_*.json"))
    assert len(metas) == 2, f"expected two timeframe metadata files, got {[str(p) for p in metas]}"

    for meta_path in metas:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        tf = raw.get("timeframe")
        assert tf in ("5m", "15m")

        assert metadata_is_v15_pipeline(meta_path, raw), (
            f"{meta_path.name} must be detectable as v15 (pipeline_{tf}_v14.pkl beside metadata)"
        )

        pip = meta_path.parent / f"pipeline_{tf}_v14.pkl"
        assert pip.is_file(), f"missing pipeline artefact: {pip}"

        feats = raw.get("features") or []
        ref = V15_FEATURES_5M if tf == "5m" else V15_FEATURES_15M
        assert feats == ref, (
            f"{meta_path}: features list must match V15_FEATURES_{'5M' if tf == '5m' else '15M'} "
            "in feature_store/feature_registry.py (train–serve parity)."
        )

        assert raw.get("training", {}).get("model_type") == "XGBClassifier"
