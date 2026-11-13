"""Load a swinging research bundle and refuse anything that can place orders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

from research.swinging.export_bundle import file_sha256


def load_research_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Load manifest, schema, and models for a research-only swinging bundle.

    Args:
        bundle_dir: Directory produced by ``write_research_bundle``.

    Returns:
        Manifest, artifact, and the feature column list.

    Raises:
        FileNotFoundError: If a required file is missing.
        RuntimeError: If orders are enabled, promotion is not ``research``,
            the schema disagrees with the manifest, or the checksum mismatches.
    """
    manifest_path = bundle_dir / "manifest.json"
    model_path = bundle_dir / "models.joblib"
    schema_path = bundle_dir / "feature_schema.json"
    if not manifest_path.is_file() or not model_path.is_file() or not schema_path.is_file():
        raise FileNotFoundError(f"swinging bundle is incomplete: {bundle_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if bool(manifest.get("orders_enabled")):
        raise RuntimeError("swinging bundle cannot enable orders")
    if manifest.get("promotion_status") != "research":
        raise RuntimeError("swinging bundle is not marked research-only")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    columns = [str(name) for name in schema.get("features") or []]
    if [str(name) for name in manifest.get("feature_columns") or []] != columns:
        raise RuntimeError("feature schema does not match the swinging manifest")
    expected = str(manifest.get("model_checksum") or "")
    actual = file_sha256(model_path)
    if expected and expected != actual:
        raise RuntimeError("swinging model checksum mismatch")
    artifact = joblib.load(model_path)
    return {"manifest": manifest, "artifact": artifact, "feature_columns": columns}


def vector_from_features(columns: list[str], features: dict[str, Any]) -> list[float]:
    """Build one model row in schema order.

    Args:
        columns: Feature schema.
        features: Snapshot or caller-supplied values.

    Returns:
        Finite floats.

    Raises:
        ValueError: If a schema column is missing.
    """
    missing = [name for name in columns if name not in features]
    if missing:
        raise ValueError(f"swinging features missing columns: {missing[:8]}")
    values: list[float] = []
    for name in columns:
        try:
            number = float(features[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"swinging feature {name} is not numeric") from exc
        if number != number:
            number = 0.0
        values.append(number)
    return values
