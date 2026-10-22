"""Direction-only development fit. Barrier labels and the later tail are unused."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import structlog

from research.forecast_30m.contract_v4 import (
    DECISION_BY_CLASS,
    DEVELOPMENT_END_EXCLUSIVE,
    DIRECTION_NAMES,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    LABEL_VERSION,
    ORIGINAL_SOURCE,
    SNAPSHOT_END,
    SPEC_VERSION,
)
from research.forecast_30m.dataset import build_direction_frames
from research.forecast_30m.inference import ORDERS_ENABLED
from research.forecast_30m.integrity import _REPO_ROOT, file_sha256
from research.forecast_30m.labels import measure_direction_theta, render_labels_v4_yaml
from research.forecast_30m.models import train_direction_xgb
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
)

logger = structlog.get_logger()
_PHASE1_AUDIT = _REPO_ROOT / "export" / "forecast_30m" / "data_audit.json"
_ORIGINAL = _REPO_ROOT / ORIGINAL_SOURCE
_EXPORT = _REPO_ROOT / "export" / "forecast_30m" / "v4"
_CONFIG = _REPO_ROOT / "research" / "forecast_30m" / "configs"


def run_research_v4() -> dict[str, Any]:
    """Measure the class-floor theta, fit direction, and write a research artifact.

    Returns:
        A JSON-safe summary. Estimators stay in the artifact directory.
    """
    development_end = pd.Timestamp(DEVELOPMENT_END_EXCLUSIVE)
    snapshot_end = pd.Timestamp(SNAPSHOT_END)
    source_hash = _assert_original_snapshot()
    candles = pd.read_parquet(_ORIGINAL)
    report = measure_direction_theta(
        candles,
        holdout_start=int(development_end.timestamp()),
    )
    report["spec_version"] = SPEC_VERSION
    _EXPORT.mkdir(parents=True, exist_ok=True)
    _write_json(_EXPORT / "label_report.json", report)
    (_CONFIG / "labels_v4.yaml").write_text(render_labels_v4_yaml(report), encoding="utf-8")
    theta_row = report["theta"]["selected"]
    if theta_row is None:
        trained = {
            "tasks": {
                "direction": {
                    "gate4": {"passed": False, "reason": "no_theta_passed"},
                    "bundle": None,
                }
            }
        }
        development = pd.DataFrame()
    else:
        development = build_direction_frames(
            candles,
            theta=float(theta_row["theta"]),
            development_end=development_end,
        )
        assert_development_only(development, development_end)
        assert_outside_embargo(development, development_end, snapshot_end)
        development.to_parquet(_EXPORT / "dataset_development.parquet", index=False)
        logger.info("forecast_30m_v4_development", rows=int(len(development)))
        trained = train_direction_xgb(
            development,
            holdout_start=development_end,
            embargo_end=snapshot_end,
            feature_columns=FEATURE_COLUMNS,
        )
    public = _public_training(trained)
    _write_json(_EXPORT / "phase4_development.json", public)
    artifact = _write_artifact(trained, report, source_hash)
    passed = bool(trained["tasks"]["direction"].get("gate4", {}).get("passed"))
    logger.info(
        "forecast_30m_v4_complete",
        gate4=passed,
        artifact=str(artifact),
        orders_enabled=ORDERS_ENABLED,
    )
    return {
        "gate4_passed": {"direction": passed},
        "theta": None if theta_row is None else theta_row["theta"],
        "development_rows": int(len(development)),
        "artifact": artifact.as_posix(),
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "decision_by_class": dict(DECISION_BY_CLASS),
    }


def _assert_original_snapshot() -> str:
    audit = json.loads(_PHASE1_AUDIT.read_text(encoding="utf-8"))
    source_hash = file_sha256(_ORIGINAL)
    if source_hash != audit["source_sha256"]:
        raise RuntimeError("OHLCV snapshot hash does not match the Phase 1 audit")
    if not audit["source_decision"]["accepted"]:
        raise RuntimeError("Phase 1 did not accept this OHLCV snapshot")
    return source_hash


def _write_artifact(
    trained: Mapping[str, Any],
    report: Mapping[str, Any],
    source_hash: str,
) -> Path:
    destination = _EXPORT / "artifacts" / LABEL_VERSION
    destination.mkdir(parents=True, exist_ok=True)
    payload = trained["tasks"]["direction"]
    models = {}
    if payload.get("bundle") is not None:
        models["direction"] = payload["bundle"]
    joblib.dump(models, destination / "models.joblib")
    theta_row = report["theta"]["selected"]
    manifest = {
        "spec_version": SPEC_VERSION,
        "label_version": LABEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "source_sha256": source_hash,
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "snapshot_end": SNAPSHOT_END,
        "entry": "next_open",
        "label_selection": {
            "theta": None if theta_row is None else theta_row["theta"],
            "theta_reason": report["theta"]["reason"],
        },
        "decision_by_class": {
            DIRECTION_NAMES[code]: name for code, name in DECISION_BY_CLASS.items()
        },
        "gate4_passed": {
            "direction": bool(payload.get("gate4", {}).get("passed")),
        },
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "targets_in_artifact": sorted(models),
    }
    _write_json(destination / "manifest.json", manifest)
    return destination


def _public_training(trained: Mapping[str, Any]) -> dict[str, Any]:
    public = {}
    for task, payload in trained["tasks"].items():
        public[task] = {key: value for key, value in payload.items() if key != "bundle"}
    return _json_ready(public)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(payload), indent=2) + "\n", encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return _json_ready(value.tolist())
    return value


if __name__ == "__main__":
    run_research_v4()
