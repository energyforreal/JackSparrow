"""Direction-policy development fit. Confirmation is scored only after the gate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import structlog

from research.forecast_30m.contract_v5 import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_BLOCK_BARS,
    BOOTSTRAP_DRAWS,
    DECISION_BY_CLASS,
    DEVELOPMENT_END_EXCLUSIVE,
    DIRECTION_NAMES,
    EXTENDED_SOURCE,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    FORECAST_BUNDLE_DIR_NAME,
    HORIZON_BARS,
    LABEL_VERSION,
    ORIGINAL_SOURCE,
    ROUND_TRIP_COST,
    SEED,
    SNAPSHOT_END,
    SPEC_VERSION,
)
from research.forecast_30m.dataset import (
    build_direction_confirmation_frames,
    build_direction_frames,
)
from research.forecast_30m.evaluation import (
    buy_and_hold_bar_returns,
    confirmation_gate,
    one_position_direction_policy,
)
from research.forecast_30m.integrity import _REPO_ROOT, file_sha256
from research.forecast_30m.labels import measure_direction_theta, render_labels_v5_yaml
from research.forecast_30m.models import predict_bundle, train_direction_policy_xgb
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
)

logger = structlog.get_logger()
_PHASE1_AUDIT = _REPO_ROOT / "export" / "forecast_30m" / "data_audit.json"
_ORIGINAL = _REPO_ROOT / ORIGINAL_SOURCE
_EXTENDED = _REPO_ROOT / EXTENDED_SOURCE
_EXPORT = _REPO_ROOT / "export" / "forecast_30m" / "v5"
_CONFIG = _REPO_ROOT / "research" / "forecast_30m" / "configs"
_AGENT_BUNDLE = _REPO_ROOT / "agent" / "model_storage" / FORECAST_BUNDLE_DIR_NAME


def run_research_v5() -> dict[str, Any]:
    """Measure theta, fit the direction policy, and score confirmation once.

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
    theta_row = report["theta"]["selected"]
    if theta_row is None:
        trained = {
            "gate": {"passed": False, "reasons": ["no_theta_passed"]},
            "bundle": None,
            "probability_floor": None,
            "fold_stats": [],
            "orders_enabled": False,
        }
        development = pd.DataFrame()
    else:
        development = build_direction_frames(
            candles,
            theta=float(theta_row["theta"]),
            development_end=development_end,
            feature_columns=FEATURE_COLUMNS,
            feature_version=FEATURE_VERSION,
            label_version=LABEL_VERSION,
        )
        assert_development_only(development, development_end)
        assert_outside_embargo(development, development_end, snapshot_end)
        development.to_parquet(_EXPORT / "dataset_development.parquet", index=False)
        logger.info("forecast_30m_v5_development", rows=int(len(development)))
        trained = train_direction_policy_xgb(
            development,
            holdout_start=development_end,
            embargo_end=snapshot_end,
            feature_columns=FEATURE_COLUMNS,
        )
    report["probability_floor"] = trained.get("probability_floor")
    _write_json(_EXPORT / "label_report.json", report)
    (_CONFIG / "labels_v5.yaml").write_text(render_labels_v5_yaml(report), encoding="utf-8")
    _write_json(_EXPORT / "phase4_development.json", _public_training(trained))
    confirmation_report = _maybe_score_confirmation(
        trained,
        theta=None if theta_row is None else float(theta_row["theta"]),
        snapshot_end=snapshot_end,
    )
    _write_json(_EXPORT / "phase5_confirmation.json", confirmation_report)
    artifact = _write_artifact(trained, report, confirmation_report, source_hash)
    promoted = _maybe_promote(artifact, bool(trained.get("gate", {}).get("passed")))
    passed = bool(trained.get("gate", {}).get("passed"))
    orders_enabled = bool(passed)
    logger.info(
        "forecast_30m_v5_complete",
        gate=passed,
        artifact=str(artifact),
        orders_enabled=orders_enabled,
        promoted_to_agent=promoted,
        confirmation_scored=bool(confirmation_report.get("scored")),
    )
    return {
        "gate_passed": passed,
        "theta": None if theta_row is None else theta_row["theta"],
        "probability_floor": trained.get("probability_floor"),
        "development_rows": int(len(development)),
        "artifact": artifact.as_posix(),
        "orders_enabled": orders_enabled,
        "promoted_to_agent": promoted,
        "confirmation_scored": bool(confirmation_report.get("scored")),
        "decision_by_class": dict(DECISION_BY_CLASS),
    }


def _maybe_score_confirmation(
    trained: Mapping[str, Any],
    *,
    theta: float | None,
    snapshot_end: pd.Timestamp,
) -> dict[str, Any]:
    """Score the frozen tail only after the development gate passes."""
    gate = trained.get("gate") or {}
    if not gate.get("passed"):
        reasons = list(gate.get("reasons") or ["development_gate_failed"])
        return {
            "scored": False,
            "labels_read": False,
            "reason": str(reasons[0]),
            "development_reasons": reasons,
        }
    bundle = trained.get("bundle")
    threshold = trained.get("probability_floor")
    if bundle is None or threshold is None:
        return {
            "scored": False,
            "labels_read": False,
            "reason": "bundle_or_floor_missing",
        }
    if not _EXTENDED.is_file():
        return {
            "scored": False,
            "labels_read": False,
            "reason": "missing_extended_snapshot",
        }
    candles = pd.read_parquet(_EXTENDED)
    confirmation = build_direction_confirmation_frames(
        candles,
        theta=float(theta),
        snapshot_end=snapshot_end,
        feature_columns=FEATURE_COLUMNS,
    )
    if confirmation.empty:
        return {
            "scored": True,
            "labels_read": True,
            "passed": False,
            "reason": "insufficient_confirmation_window",
            "trades": 0,
        }
    features = list(bundle["features"])
    proba = predict_bundle(
        bundle, confirmation.loc[:, features].to_numpy(dtype=np.float64)
    )
    origin, length, open_first, close_last = _confirmation_window(candles, snapshot_end)
    policy = one_position_direction_policy(
        confirmation,
        proba,
        threshold=float(threshold),
        cost=ROUND_TRIP_COST,
        horizon_bars=HORIZON_BARS,
        series_length=length,
        series_origin=origin,
    )
    buy_hold = buy_and_hold_bar_returns(
        open_first,
        close_last,
        n_bars=length,
        cost=ROUND_TRIP_COST,
    )
    decision = confirmation_gate(
        policy["bar_returns"],
        buy_hold,
        trades=int(policy["trades"]),
        expectancy=policy["expectancy"],
        profit_factor=policy["profit_factor"],
        max_drawdown=policy["max_drawdown"],
        block_length=BOOTSTRAP_BLOCK_BARS,
        draws=BOOTSTRAP_DRAWS,
        seed=SEED,
        alpha=BOOTSTRAP_ALPHA,
    )
    decision["scored"] = True
    decision["labels_read"] = True
    decision["buy_and_hold_return"] = float(buy_hold.sum())
    confirmation.to_parquet(_EXPORT / "dataset_confirmation.parquet", index=False)
    return _json_ready(decision)


def _confirmation_window(
    candles: pd.DataFrame,
    snapshot_end: pd.Timestamp,
) -> tuple[int, int, float, float]:
    stamps = pd.to_datetime(candles["time"], utc=True)
    mask = stamps > snapshot_end
    if not bool(mask.any()):
        return 0, 0, float("nan"), float("nan")
    positions = np.flatnonzero(mask.to_numpy())
    origin = int(positions[0])
    length = int(positions.size)
    open_first = float(candles["open"].to_numpy(dtype=np.float64)[origin])
    close_last = float(candles["close"].to_numpy(dtype=np.float64)[positions[-1]])
    return origin, length, open_first, close_last


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
    confirmation_report: Mapping[str, Any],
    source_hash: str,
) -> Path:
    destination = _EXPORT / "artifacts" / LABEL_VERSION
    destination.mkdir(parents=True, exist_ok=True)
    models = {}
    if trained.get("bundle") is not None:
        models["direction"] = trained["bundle"]
    joblib.dump(models, destination / "models.joblib")
    theta_row = report["theta"]["selected"]
    passed = bool(trained.get("gate", {}).get("passed"))
    manifest = {
        "spec_version": SPEC_VERSION,
        "label_version": LABEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "source_sha256": source_hash,
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "snapshot_end": SNAPSHOT_END,
        "entry": "next_open",
        "probability_floor": trained.get("probability_floor"),
        "label_selection": {
            "theta": None if theta_row is None else theta_row["theta"],
            "theta_reason": report["theta"]["reason"],
            "probability_floor": trained.get("probability_floor"),
            "round_trip_cost": ROUND_TRIP_COST,
        },
        "decision_by_class": {
            DIRECTION_NAMES[code]: name for code, name in DECISION_BY_CLASS.items()
        },
        "development_gate_passed": passed,
        "confirmation_scored": bool(confirmation_report.get("scored", False)),
        "confirmation_passed": bool(confirmation_report.get("passed", False)),
        "orders_enabled": bool(passed),
        "promoted_to_agent": False,
        "targets_in_artifact": sorted(models),
    }
    _write_json(destination / "manifest.json", manifest)
    return destination


def _maybe_promote(artifact: Path, passed: bool) -> bool:
    """Copy a passing bundle into live model storage. Failures stay out."""
    if not passed:
        return False
    _AGENT_BUNDLE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact / "manifest.json", _AGENT_BUNDLE / "manifest.json")
    shutil.copy2(artifact / "models.joblib", _AGENT_BUNDLE / "models.joblib")
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    manifest["promoted_to_agent"] = True
    _write_json(artifact / "manifest.json", manifest)
    _write_json(_AGENT_BUNDLE / "manifest.json", manifest)
    logger.info("forecast_30m_v5_promoted", destination=str(_AGENT_BUNDLE))
    return True


def _public_training(trained: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in trained.items()
        if key not in {"bundle", "bundles"}
    }
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
    run_research_v5()
