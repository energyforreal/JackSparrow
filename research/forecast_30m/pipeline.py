"""Run the v2 measurement and fit. The v1 holdout is not scored again."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import structlog

from research.forecast_30m.contract import (
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    LABEL_VERSION,
    ROUND_TRIP_COST,
    SPEC_VERSION,
)
from research.forecast_30m.dataset import build_supervised_frames
from research.forecast_30m.evaluation import choose_thresholds, gate5_passed
from research.forecast_30m.inference import ORDERS_ENABLED
from research.forecast_30m.integrity import _REPO_ROOT, file_sha256
from research.forecast_30m.labels import measure_label_grid, render_labels_yaml
from research.forecast_30m.models import predict_bundle, score_frozen, train_development
from research.forecast_30m.validation import assert_development_only, development_blocks

logger = structlog.get_logger()
_AUDIT = _REPO_ROOT / "export" / "forecast_30m" / "data_audit.json"
_SOURCE = _REPO_ROOT / "export" / "fusion_diagnostics" / "btcusd_30m_raw.parquet"
_EXPORT = _REPO_ROOT / "export" / "forecast_30m" / "v2"
_CONFIG = _REPO_ROOT / "research" / "forecast_30m" / "configs"


def run_research() -> dict[str, Any]:
    """Execute the measurement, fit, single holdout score, and artifact write.

    Returns:
        A JSON-safe summary. Model objects stay in the artifact directory.
    """
    audit = json.loads(_AUDIT.read_text(encoding="utf-8"))
    source_hash = file_sha256(_SOURCE)
    if source_hash != audit["source_sha256"]:
        raise RuntimeError("OHLCV snapshot hash does not match the Phase 1 audit")
    if not audit["source_decision"]["accepted"]:
        raise RuntimeError("Phase 1 did not accept this OHLCV snapshot")
    holdout_start = pd.Timestamp(audit["split"]["holdout_start"])
    candles = pd.read_parquet(_SOURCE)
    logger.info("forecast_30m_measure_labels", rows=int(len(candles)))
    report = measure_label_grid(
        candles,
        holdout_start=int(holdout_start.timestamp()),
        cost=ROUND_TRIP_COST,
    )
    _write_json(_EXPORT / "label_report.json", report)
    (_CONFIG / "labels.yaml").write_text(render_labels_yaml(report), encoding="utf-8")
    theta, tp_mult, sl_mult, tasks = _selected_tasks(report)
    logger.info(
        "forecast_30m_labels_frozen",
        theta=theta,
        tp_mult=tp_mult,
        sl_mult=sl_mult,
        tasks=tasks,
        development_rows=report["development_rows"],
    )
    development, holdout = build_supervised_frames(
        candles,
        theta=theta,
        tp_mult=tp_mult,
        sl_mult=sl_mult,
        holdout_start=holdout_start,
    )
    assert_development_only(development, holdout_start)
    barrier_row = report["barrier"]["selected"]
    if barrier_row is not None and barrier_row.get("breakeven_precision") is not None:
        breakeven = float(barrier_row["breakeven_precision"])
        development["breakeven_precision"] = breakeven
        holdout["breakeven_precision"] = breakeven
    development.to_parquet(_EXPORT / "dataset_development.parquet", index=False)
    holdout.to_parquet(_EXPORT / "dataset_holdout.parquet", index=False)
    trained = train_development(development, holdout_start=holdout_start, tasks=tasks)
    passed = {
        task: bool(payload["gate4"]["passed"])
        for task, payload in trained["tasks"].items()
    }
    _write_json(_EXPORT / "phase4_development.json", _public_training(trained))
    holdout_report = _maybe_score_holdout(
        trained,
        holdout,
        passed,
        holdout_start=holdout_start,
    )
    _write_json(_EXPORT / "phase5_holdout.json", holdout_report)
    artifact = _write_artifact(trained, report, audit, passed, holdout_report, source_hash)
    logger.info(
        "forecast_30m_pipeline_complete",
        gate4=passed,
        gate5=holdout_report.get("gate5", {}).get("passed"),
        holdout_scored=holdout_report["scored"],
        artifact=str(artifact),
    )
    return {
        "gate4_passed": passed,
        "holdout_scored": holdout_report["scored"],
        "gate5_passed": bool(holdout_report.get("gate5", {}).get("passed", False)),
        "artifact": artifact.as_posix(),
    }


def _selected_tasks(
    report: Mapping[str, Any],
) -> tuple[float | None, float | None, float | None, list[str]]:
    tasks = ["return"]
    theta_row = report["theta"]["selected"]
    barrier_row = report["barrier"]["selected"]
    theta = None if theta_row is None else float(theta_row["theta"])
    if theta is not None:
        tasks.append("direction")
    if barrier_row is None:
        return theta, None, None, tasks
    tasks.extend(["long_tp", "short_tp"])
    return theta, float(barrier_row["tp_mult"]), float(barrier_row["sl_mult"]), tasks


def _maybe_score_holdout(
    trained: Mapping[str, Any],
    holdout: pd.DataFrame,
    passed: Mapping[str, bool],
    *,
    holdout_start: pd.Timestamp,
) -> dict[str, Any]:
    if _holdout_already_scored():
        return {
            "scored": False,
            "reason": "holdout_already_scored_once",
            "gate4_passed": dict(passed),
            "holdout_rows_on_disk": int(len(holdout)),
        }
    if not any(passed.values()):
        return {
            "scored": False,
            "reason": "gate4_failed_for_every_target",
            "holdout_rows_on_disk": int(len(holdout)),
        }
    if (pd.to_datetime(holdout["time"], utc=True) < holdout_start).any():
        raise RuntimeError("holdout frame contains a development timestamp")
    scores = {}
    for task, did_pass in passed.items():
        if not did_pass:
            continue
        try:
            scores[task] = score_frozen(trained["tasks"][task]["bundle"], holdout)
        except ValueError as exc:
            scores[task] = {"error": str(exc)}
    policy = _score_policy(trained, holdout, passed)
    return {"scored": True, "targets": scores, "gate5": policy}


def _score_policy(
    trained: Mapping[str, Any],
    holdout: pd.DataFrame,
    passed: Mapping[str, bool],
) -> dict[str, Any]:
    if not (passed.get("long_tp") and passed.get("short_tp")):
        return {"passed": False, "reasons": ["barrier_heads_not_approved"], "scored": False}
    long_bundle = trained["tasks"]["long_tp"]["bundle"]
    short_bundle = trained["tasks"]["short_tp"]["bundle"]
    calibration = _calibration_frame(pd.read_parquet(_EXPORT / "dataset_development.parquet"))
    long_cal = predict_bundle(
        long_bundle, calibration.loc[:, long_bundle["features"]].to_numpy(dtype=np.float64)
    )
    short_cal = predict_bundle(
        short_bundle, calibration.loc[:, short_bundle["features"]].to_numpy(dtype=np.float64)
    )
    choice = choose_thresholds(
        calibration,
        long_probability=long_cal,
        short_probability=short_cal,
    )
    if choice["selected"] is None:
        return {
            "passed": False,
            "reasons": [choice["reason"]],
            "scored": False,
            "thresholds": choice,
        }
    long_hold = predict_bundle(
        long_bundle, holdout.loc[:, long_bundle["features"]].to_numpy(dtype=np.float64)
    )
    short_hold = predict_bundle(
        short_bundle, holdout.loc[:, short_bundle["features"]].to_numpy(dtype=np.float64)
    )
    decision = gate5_passed(
        holdout,
        {"long": long_hold, "short": short_hold},
        choice["selected"],
    )
    decision["scored"] = True
    decision["thresholds"] = choice["selected"]
    return decision


def _holdout_already_scored() -> bool:
    """The v1 cut was scored once. A later snapshot must clear that status first."""
    text = (_CONFIG / "splits.yaml").read_text(encoding="utf-8")
    return "status: scored_once" in text


def _calibration_frame(development: pd.DataFrame) -> pd.DataFrame:
    blocks = development_blocks(development["bar_index"].to_numpy(dtype=np.int64))
    return development.iloc[blocks["calibration"]].reset_index(drop=True)


def _write_artifact(
    trained: Mapping[str, Any],
    report: Mapping[str, Any],
    audit: Mapping[str, Any],
    passed: Mapping[str, bool],
    holdout_report: Mapping[str, Any],
    source_hash: str,
) -> Path:
    destination = _EXPORT / "artifacts" / LABEL_VERSION
    destination.mkdir(parents=True, exist_ok=True)
    models = {
        task: payload["bundle"]
        for task, payload in trained["tasks"].items()
        if payload["bundle"] is not None
    }
    joblib.dump(models, destination / "models.joblib")
    gate5 = holdout_report.get("gate5") or {}
    theta_row = report["theta"]["selected"]
    barrier_row = report["barrier"]["selected"]
    manifest = {
        "spec_version": SPEC_VERSION,
        "label_version": LABEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "source_sha256": source_hash,
        "holdout_start": audit["split"]["holdout_start"],
        "label_selection": {
            "theta": None if theta_row is None else theta_row["theta"],
            "theta_reason": report["theta"]["reason"],
            "tp_mult": None if barrier_row is None else barrier_row["tp_mult"],
            "sl_mult": None if barrier_row is None else barrier_row["sl_mult"],
            "barrier_reason": report["barrier"]["reason"],
            "round_trip_cost": ROUND_TRIP_COST,
        },
        "gate4_passed": dict(passed),
        "gate5_passed": bool(gate5.get("passed", False)),
        "holdout_scored": bool(holdout_report.get("scored", False)),
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
    return public


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
    run_research()
