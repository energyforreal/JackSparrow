"""Load a versioned research artifact and forecast the latest closed bar.

This module cannot place an order and does not import the exchange gateway.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from research.forecast_30m.contract import DIRECTION_NAMES
from research.forecast_30m.features import add_features
from research.forecast_30m.models import predict_bundle

ORDERS_ENABLED = False


def load_artifact(path: Path) -> dict[str, Any]:
    """Load a forecast artifact directory.

    Args:
        path: Directory containing ``manifest.json`` and ``models.joblib``.

    Returns:
        Manifest plus the in-memory model bundles.
    """
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    models = joblib.load(path / "models.joblib")
    return {"manifest": manifest, "models": models}


def predict_latest(artifact: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """Forecast from the last row of a causal OHLCV frame.

    Args:
        artifact: Output of :func:`load_artifact`.
        frame: Closed candles ending at the signal bar. Must include warmup.

    Returns:
        Direction, forward return, both TP-first probabilities, and
        ``orders_enabled=False``.

    Raises:
        ValueError: If the latest bar does not have a complete feature row.
    """
    featured = add_features(frame)
    latest = featured.iloc[-1]
    if not bool(latest["feature_row_ok"]):
        raise ValueError("latest bar does not have a complete causal feature row")
    manifest = artifact["manifest"]
    models = artifact["models"]
    direction = None
    forward = None
    long_probability = None
    short_probability = None
    if "direction" in models:
        proba = _one_row(models["direction"], featured)
        direction = DIRECTION_NAMES[int(np.argmax(proba))]
    if "return" in models:
        forward = float(_one_row(models["return"], featured)[0])
    if "long_tp" in models:
        long_probability = float(_one_row(models["long_tp"], featured)[0])
    if "short_tp" in models:
        short_probability = float(_one_row(models["short_tp"], featured)[0])
    return {
        "direction": direction,
        "forward_return_24": forward,
        "long_tp_first_probability": long_probability,
        "short_tp_first_probability": short_probability,
        "orders_enabled": ORDERS_ENABLED,
        "promoted_to_agent": False,
        "gate4_passed": dict(manifest.get("gate4_passed") or {}),
        "gate5_passed": bool(manifest.get("gate5_passed", False)),
    }


def _one_row(bundle: dict[str, Any], featured: pd.DataFrame) -> np.ndarray:
    columns = list(bundle["features"])
    features = featured.iloc[[-1]].loc[:, columns].to_numpy(dtype=np.float64)
    return np.asarray(predict_bundle(bundle, features))
