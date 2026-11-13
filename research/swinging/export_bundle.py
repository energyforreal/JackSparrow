"""Research bundle export. Bundles cannot enable orders or enter model storage."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import joblib

from research.swinging.contract import (
    COLAB_DATA_ROOT,
    ORDERS_ENABLED,
    PROMOTION_STATUS_RESEARCH,
    SPEC_VERSION,
)


def assert_research_destination(path: Path) -> None:
    """Refuse a write into the live model directory.

    Args:
        path: Proposed bundle or zip path.

    Raises:
        RuntimeError: If a path part is ``model_storage``.
    """
    if "model_storage" in {part.lower() for part in path.parts}:
        raise RuntimeError(f"refusing to write a research bundle under model storage: {path}")


def file_sha256(path: Path) -> str:
    """Hash a file.

    Args:
        path: File to read.

    Returns:
        Hex sha256.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_research_bundle(
    directory: Path | str,
    artifact: dict[str, Any],
    *,
    task: str,
    metrics: dict[str, Any],
    dataset_version: str,
    training_period: dict[str, str],
) -> Path:
    """Write a research-only model bundle.

    Args:
        directory: Destination directory on the local disk.
        artifact: Fitted models and feature column list.
        task: ``setup_effectiveness`` or ``sr_effectiveness``.
        metrics: Validation and sealed-test metrics.
        dataset_version: Manifest version or checksum of the training rows.
        training_period: Earliest and latest training timestamps.

    Returns:
        The bundle directory.

    Raises:
        RuntimeError: If the destination is inside model storage.
    """
    destination = Path(directory)
    assert_research_destination(destination)
    destination.mkdir(parents=True, exist_ok=True)
    model_path = destination / "models.joblib"
    joblib.dump(artifact, model_path)
    columns = list(artifact.get("feature_columns") or [])
    schema = {
        "spec_version": SPEC_VERSION,
        "task": task,
        "features": columns,
        "feature_count": len(columns),
    }
    (destination / "feature_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    calibration = {
        "method": "isotonic" if artifact.get("calibrator") is not None else "none",
        "positive_class": artifact.get("positive_class"),
    }
    (destination / "calibration.json").write_text(
        json.dumps(calibration, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "spec_version": SPEC_VERSION,
        "task": task,
        "model_name": f"jacksparrow_{task}_BTCUSD",
        "orders_enabled": ORDERS_ENABLED,
        "promotion_status": PROMOTION_STATUS_RESEARCH,
        "contributes_to_consensus": False,
        "feature_columns": columns,
        "dataset_version": dataset_version,
        "training_period": training_period,
        "validation_metrics": metrics.get("validation", {}),
        "test_metrics": metrics.get("test", {}),
        "model_checksum": file_sha256(model_path),
        "classifier_algorithm": artifact.get("classifier_algorithm"),
        "regressor_algorithm": artifact.get("regressor_algorithm"),
        "sealed_start": artifact.get("sealed_start"),
    }
    if manifest["orders_enabled"] is not False or manifest["promotion_status"] != "research":
        raise RuntimeError("research export tried to enable orders")
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return destination


def zip_directory(directory: Path, zip_path: Path) -> Path:
    """Zip a bundle for a manual download from Colab.

    Args:
        directory: Bundle directory.
        zip_path: Destination zip on the local disk.

    Returns:
        ``zip_path``.
    """
    assert_research_destination(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory.parent).as_posix())
    return zip_path


def export_download_zip(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    task: str = "setup_effectiveness",
) -> str:
    """Copy an experiment artifact into a downloadable research zip.

    Args:
        root: Local dataset root containing ``experiments``.
        task: Experiment directory name.

    Returns:
        Zip path.
    """
    dataset = Path(root)
    source = dataset / "experiments" / task / "models.joblib"
    artifact = joblib.load(source)
    comparison_path = dataset / "experiments" / "comparison.json"
    metrics: dict[str, Any] = {}
    if comparison_path.is_file():
        metrics = {"validation": json.loads(comparison_path.read_text(encoding="utf-8"))}
    bundle = write_research_bundle(
        dataset / "export" / task,
        artifact,
        task=task,
        metrics=metrics,
        dataset_version=task,
        training_period={"earliest": "", "latest": ""},
    )
    zip_path = zip_directory(bundle, dataset / "export" / f"{task}.zip")
    return str(zip_path)
