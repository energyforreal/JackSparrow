"""Pipeline path resolution prefers latest adaptive artifact."""

import json
from pathlib import Path

from agent.models.pipeline_v15_node import metadata_is_v15_pipeline, resolve_v15_pipeline_path


def test_resolve_v15_pipeline_path_prefers_latest(tmp_path: Path) -> None:
    meta = tmp_path / "metadata_BTCUSD_5m.json"
    meta.write_text(
        json.dumps(
            {
                "timeframe": "5m",
                "training": {"model_type": "XGBClassifier"},
                "features": ["a"],
            }
        ),
        encoding="utf-8",
    )
    legacy = tmp_path / "pipeline_5m_v14.pkl"
    latest = tmp_path / "pipeline_5m_latest.pkl"
    legacy.write_bytes(b"x")
    assert resolve_v15_pipeline_path(meta, "5m") == legacy
    latest.write_bytes(b"y")
    assert resolve_v15_pipeline_path(meta, "5m") == latest


def test_resolve_v15_pipeline_path_prefers_active_json(tmp_path: Path) -> None:
    meta = tmp_path / "metadata_BTCUSD_5m.json"
    meta.write_text(
        json.dumps(
            {
                "timeframe": "5m",
                "training": {"model_type": "XGBClassifier"},
                "features": ["a"],
            }
        ),
        encoding="utf-8",
    )
    latest = tmp_path / "pipeline_5m_latest.pkl"
    versioned = tmp_path / "pipeline_5m_v_auto_99.pkl"
    latest.write_bytes(b"latest")
    versioned.write_bytes(b"versioned")
    active = tmp_path / "pipeline_5m_active.json"
    active.write_text(
        json.dumps({"artifact": "pipeline_5m_v_auto_99.pkl"}),
        encoding="utf-8",
    )
    assert resolve_v15_pipeline_path(meta, "5m") == versioned


def test_metadata_is_v15_pipeline_accepts_latest_only(tmp_path: Path) -> None:
    meta = tmp_path / "metadata_BTCUSD_15m.json"
    meta.write_text(
        json.dumps(
            {
                "timeframe": "15m",
                "training": {"model_type": "XGBClassifier"},
                "features": ["a"],
            }
        ),
        encoding="utf-8",
    )
    raw = json.loads(meta.read_text(encoding="utf-8"))
    assert metadata_is_v15_pipeline(meta, raw) is False
    (tmp_path / "pipeline_15m_latest.pkl").write_bytes(b"p")
    raw2 = json.loads(meta.read_text(encoding="utf-8"))
    assert metadata_is_v15_pipeline(meta, raw2) is True
