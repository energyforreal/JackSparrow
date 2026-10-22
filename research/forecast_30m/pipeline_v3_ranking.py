"""Development-only ranking of v3 events. Confirmation labels are not read."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import structlog

from research.forecast_30m.contract_v3 import (
    DEVELOPMENT_END_EXCLUSIVE,
    FEATURE_COLUMNS,
    FEATURE_VERSION,
    LABEL_VERSION,
    RANKING_VERSION,
    SNAPSHOT_END,
    SPEC_VERSION,
)
from research.forecast_30m.inference import ORDERS_ENABLED
from research.forecast_30m.integrity import _REPO_ROOT
from research.forecast_30m.models import rank_development_events
from research.forecast_30m.validation import (
    assert_development_only,
    assert_outside_embargo,
)

logger = structlog.get_logger()
_EXPORT = _REPO_ROOT / "export" / "forecast_30m" / "v3"
_DEVELOPMENT = _EXPORT / "dataset_development.parquet"
_RANKING = _EXPORT / "ranking"


def run_ranking() -> dict[str, Any]:
    """Rank existing development events. This does not score confirmation.

    Returns:
        A JSON-safe summary. Estimators stay in the ranking directory.
    """
    if not _DEVELOPMENT.exists():
        raise FileNotFoundError(
            "v3 development parquet is missing; run pipeline_v3 first"
        )
    development_end = pd.Timestamp(DEVELOPMENT_END_EXCLUSIVE)
    snapshot_end = pd.Timestamp(SNAPSHOT_END)
    frame = pd.read_parquet(_DEVELOPMENT)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    assert_development_only(frame, development_end)
    assert_outside_embargo(frame, development_end, snapshot_end)
    logger.info("forecast_30m_v3_ranking_start", rows=int(len(frame)))
    ranked = rank_development_events(
        frame,
        holdout_start=development_end,
        embargo_end=snapshot_end,
    )
    public = _public_ranking(ranked)
    _write_json(_RANKING / "phase4_ranking.json", public)
    artifact = _write_artifact(ranked, public)
    logger.info(
        "forecast_30m_v3_ranking_complete",
        statistical_long=public["statistical"]["long"]["passed"],
        statistical_short=public["statistical"]["short"]["passed"],
        economic=public["economic"]["passed"],
        confirmation_scored=False,
        artifact=str(artifact),
    )
    return {
        "statistical": public["statistical"],
        "economic_passed": bool(public["economic"]["passed"]),
        "economic_reasons": list(public["economic"].get("reasons") or []),
        "always_in": public["always_in"],
        "oof_rows": public["oof_rows"],
        "confirmation_scored": False,
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "artifact": artifact.as_posix(),
    }


def _write_artifact(ranked: Mapping[str, Any], public: Mapping[str, Any]) -> Path:
    destination = _RANKING / "artifacts" / RANKING_VERSION
    destination.mkdir(parents=True, exist_ok=True)
    bundles = dict(ranked.get("bundles") or {})
    joblib.dump(bundles, destination / "models.joblib")
    manifest = {
        "spec_version": SPEC_VERSION,
        "label_version": LABEL_VERSION,
        "ranking_version": RANKING_VERSION,
        "feature_version": FEATURE_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "development_end_exclusive": DEVELOPMENT_END_EXCLUSIVE,
        "snapshot_end": SNAPSHOT_END,
        "statistical_passed": {
            "long": bool(public["statistical"]["long"]["passed"]),
            "short": bool(public["statistical"]["short"]["passed"]),
        },
        "economic_passed": bool(public["economic"]["passed"]),
        "confirmation_scored": False,
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "targets_in_artifact": sorted(bundles),
    }
    _write_json(destination / "manifest.json", manifest)
    return destination


def _public_ranking(ranked: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in ranked.items()
        if key not in {"bundles", "bundle"}
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
    run_ranking()
