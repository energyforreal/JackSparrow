"""Adaptive model registry persistence tests."""

import json
from pathlib import Path

import joblib
import pytest
from xgboost import XGBClassifier

from agent.learning.adaptive.model_registry import (
    find_metadata_path,
    save_accepted_adaptive_pipeline,
)


def test_save_accepted_adaptive_pipeline_writes_files(tmp_path: Path) -> None:
    meta = tmp_path / "metadata_BTCUSD_5m.json"
    meta.write_text(
        json.dumps(
            {
                "model_name": "t",
                "timeframe": "5m",
                "features": ["f0"],
                "training": {"model_type": "XGBClassifier"},
            }
        ),
        encoding="utf-8",
    )
    clf = XGBClassifier(
        n_estimators=3,
        max_depth=2,
        objective="multi:softprob",
        num_class=3,
    )
    clf.fit([[0.0], [1.0], [2.0]], [0, 1, 2])
    pipe = {
        "model": clf,
        "features": ["f0"],
        "train_median": {"f0": 1.0},
        "meta": {"new_f1": 0.5, "old_f1": 0.4, "n_samples": 3},
    }
    paths = save_accepted_adaptive_pipeline(
        meta,
        "5m",
        pipe,
        version_tag="v_auto_test1",
        log_filename="retrain_log.json",
        scores={"new_f1": 0.5, "old_f1": 0.4, "n_samples": 3, "drifted": 6},
    )
    assert Path(paths["versioned_pkl"]).is_file()
    assert Path(paths["latest_pkl"]).is_file()
    assert Path(paths["log_path"]).is_file()
    updated = json.loads(meta.read_text(encoding="utf-8"))
    assert updated.get("train_median", {}).get("f0") == 1.0


def test_find_metadata_path_optional() -> None:
    """Smoke: find_metadata_path when MODEL_DIR exists."""
    from agent.core.config import settings

    root = Path(settings.model_dir)
    if not root.is_dir():
        pytest.skip("MODEL_DIR missing")
    p = find_metadata_path(root, "BTCUSD", "5m")
    assert p is None or "metadata_BTCUSD_5m" in p.name
