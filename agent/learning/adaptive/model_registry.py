"""Versioned adaptive pipeline saves + retrain audit log."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


def _atomic_write_json(path: Path, data: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _train_median_to_jsonable(med: Any) -> Dict[str, float]:
    if hasattr(med, "to_dict"):
        return {str(k): float(v) for k, v in med.items()}  # type: ignore[union-attr]
    if isinstance(med, dict):
        return {str(k): float(v) for k, v in med.items()}
    return {}


def save_accepted_adaptive_pipeline(
    metadata_path: Path,
    timeframe: str,
    accepted_pipeline: Dict[str, Any],
    *,
    version_tag: str,
    log_filename: str,
    scores: Dict[str, Any],
) -> Dict[str, str]:
    """Persist versioned pickle, latest pointer, metadata JSON refresh, audit log.

    Args:
        metadata_path: Path to ``metadata_BTCUSD_{tf}.json`` beside pipeline files.
        timeframe: e.g. ``5m``.
        accepted_pipeline: Dict with keys ``model``, ``features``, ``train_median``, ``meta``.
        version_tag: e.g. ``v_auto_1749823001``.
        log_filename: ``retrain_log.json`` (written next to metadata).
        scores: Extra fields for audit (old_f1, new_f1, n_samples, drifted).

    Returns:
        Paths written: versioned_pkl, latest_pkl, log_path.
    """
    try:
        import joblib
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("joblib required for adaptive pipeline save") from e

    parent = metadata_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    versioned = parent / f"pipeline_{timeframe}_{version_tag}.pkl"
    latest = parent / f"pipeline_{timeframe}_latest.pkl"

    joblib.dump(accepted_pipeline, versioned)
    joblib.dump(accepted_pipeline, latest)

    active_path = parent / f"pipeline_{timeframe}_active.json"
    active_payload = {
        "artifact": versioned.name,
        "version_tag": version_tag,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp_a = active_path.with_suffix(active_path.suffix + ".tmp")
    tmp_a.write_text(json.dumps(active_payload, indent=2), encoding="utf-8")
    tmp_a.replace(active_path)

    # Merge train_median into metadata for runtime gap-fill parity
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    tm = _train_median_to_jsonable(accepted_pipeline.get("train_median") or {})
    if tm:
        raw["train_median"] = tm
    meta = accepted_pipeline.get("meta") or {}
    if isinstance(meta, dict):
        raw.setdefault("adaptive", {})
        if isinstance(raw["adaptive"], dict):
            raw["adaptive"].update(
                {
                    "last_version": version_tag,
                    "last_retrained_at": datetime.now(timezone.utc).isoformat(),
                    **{k: meta[k] for k in ("new_f1", "old_f1", "n_samples") if k in meta},
                }
            )
    metadata_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    log_path = parent / log_filename
    entries: List[Dict[str, Any]] = []
    if log_path.is_file():
        try:
            entries = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                entries = []
        except Exception:
            entries = []
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tf": timeframe,
        "version": version_tag,
        "scores": {
            "new_f1": float(scores.get("new_f1", 0.0)),
            "old_f1": float(scores.get("old_f1", 0.0)),
        },
        "n_samples": int(scores.get("n_samples", 0)),
        "drifted_features": int(scores.get("drifted", 0)),
        "drifted_psi_features": int(scores.get("drifted_psi", 0)),
    }
    nsc = scores.get("new_scorecard")
    osc = scores.get("old_scorecard")
    if isinstance(nsc, dict):
        entry["new_scorecard"] = nsc
    if isinstance(osc, dict):
        entry["old_scorecard"] = osc
    entries.append(entry)
    _atomic_write_json(log_path, entries)

    logger.info(
        "adaptive_pipeline_saved",
        service="agent",
        component="model_registry",
        timeframe=timeframe,
        version=version_tag,
        versioned=str(versioned),
        latest=str(latest),
    )
    return {
        "versioned_pkl": str(versioned),
        "latest_pkl": str(latest),
        "log_path": str(log_path),
    }


def rollback_active_pipeline(
    metadata_path: Path,
    timeframe: str,
    log_filename: str = "retrain_log.json",
) -> Dict[str, Any]:
    """Point ``active`` + ``latest`` at the previous version from the retrain audit log."""
    parent = metadata_path.parent
    log_path = parent / log_filename
    if not log_path.is_file():
        return {"ok": False, "error": "no_log", "path": str(log_path)}
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"log_read:{e}"}
    if not isinstance(entries, list) or len(entries) < 2:
        return {"ok": False, "error": "insufficient_history"}
    prev = entries[-2]
    ver = prev.get("version")
    if not isinstance(ver, str) or not ver:
        return {"ok": False, "error": "bad_log_entry"}
    src = parent / f"pipeline_{timeframe}_{ver}.pkl"
    if not src.is_file():
        return {"ok": False, "error": "artifact_missing", "path": str(src)}
    latest = parent / f"pipeline_{timeframe}_latest.pkl"
    shutil.copyfile(src, latest)
    active_path = parent / f"pipeline_{timeframe}_active.json"
    payload = {
        "artifact": src.name,
        "version_tag": ver,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "rollback": True,
    }
    tmp_a = active_path.with_suffix(active_path.suffix + ".tmp")
    tmp_a.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_a.replace(active_path)
    logger.info(
        "adaptive_pipeline_rollback",
        service="agent",
        component="model_registry",
        timeframe=timeframe,
        version=ver,
        artifact=str(src),
    )
    return {"ok": True, "artifact": str(src), "version": ver}


def load_pipeline_bundle(pipeline_path: Path) -> Any:
    """Load joblib pipeline dict or estimator."""
    try:
        import joblib
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("joblib required") from e
    return joblib.load(pipeline_path)


def find_metadata_path(model_dir: Path, symbol: str, timeframe: str) -> Optional[Path]:
    """Locate ``metadata_{SYMBOL}_{tf}.json`` under model_dir (recursive)."""
    if not model_dir.is_dir():
        return None
    pattern = f"metadata_{symbol}_{timeframe}.json"
    matches = sorted(model_dir.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
