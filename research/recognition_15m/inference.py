"""Load the recognition checkpoint and score the latest completed window.

The result describes geometry and market state. It does not emit an order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.recognition_15m.bars import dedupe_timestamps, resample_completed_15m
from research.recognition_15m.contract import (
    ENGINEERED_CHANNELS,
    GEOMETRIC_CLASSES,
    MARKET_STATES,
    RECOGNITION_BUNDLE_DIR_NAME,
    RECOGNITION_CHECKPOINT_NAME,
    RECOGNITION_DECISION_PATH,
    SPEC_VERSION,
    STRUCTURE_TAGS,
    TCN_DILATIONS,
    TCN_HIDDEN,
)
from research.recognition_15m.dataset import stack_windows
from research.recognition_15m.features import add_engineered_features, first_finite_bar
from research.recognition_15m.labels import build_rule_card, geometry_matrix, market_labels
from research.recognition_15m.models import RecognitionTCN, _as_tensor, _to_numpy
from research.recognition_15m.splits import eligible_ends

_OHLCV = ("open", "high", "low", "close", "volume")


def recognition_checkpoint_path(model_dir: Path | str) -> Path | None:
    """Return the Colab checkpoint installed under model storage.

    Args:
        model_dir: Agent ``MODEL_DIR``.

    Returns:
        Existing checkpoint path, or ``None`` when the bundle is absent.
    """
    bundled = Path(model_dir) / RECOGNITION_BUNDLE_DIR_NAME / RECOGNITION_CHECKPOINT_NAME
    if bundled.is_file():
        return bundled
    return None


def load_recognition_checkpoint(path: Path) -> dict[str, Any]:
    """Load the TCN, its scaler, and the saved search settings.

    Args:
        path: ``tcn_colab.pt`` written by the Colab run.

    Returns:
        Model in eval mode plus the scaler and channel list.

    Raises:
        ValueError: If the checkpoint channels differ from the allow-list.
    """
    import torch

    payload = torch.load(path, map_location="cpu", weights_only=False)
    params = dict(payload.get("best_params") or {})
    channels = tuple(payload.get("channels") or ENGINEERED_CHANNELS)
    if channels != ENGINEERED_CHANNELS:
        raise ValueError("recognition checkpoint channels differ from the allow-list")
    hidden = int(params.get("hidden") or TCN_HIDDEN)
    dilations = tuple(int(item) for item in params.get("dilations") or TCN_DILATIONS)
    model = RecognitionTCN(
        in_channels=len(ENGINEERED_CHANNELS),
        n_geometry=len(GEOMETRIC_CLASSES),
        n_states=len(MARKET_STATES),
        n_tags=len(STRUCTURE_TAGS),
        hidden=hidden,
        dilations=dilations,
    )
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return {
        "model": model,
        "scaler_mean": np.asarray(payload["scaler_mean"], dtype=np.float32),
        "scaler_std": np.asarray(payload["scaler_std"], dtype=np.float32),
        "channels": channels,
        "spec_version": str(payload.get("spec_version") or SPEC_VERSION),
        "best_params": params,
        "path": str(path),
    }


def load_recognition_manifest(checkpoint: Path) -> dict[str, Any]:
    """Read the sidecar manifest when one sits beside the checkpoint."""
    manifest_path = checkpoint.parent / "manifest.json"
    if not manifest_path.is_file():
        return {
            "model_name": "jacksparrow_recognition_BTCUSD_15m",
            "spec_version": SPEC_VERSION,
            "orders_enabled": False,
        }
    return json.loads(manifest_path.read_text(encoding="utf-8-sig"))


def predict_latest(artifact: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """Score the last completed 15-minute window in a 5-minute frame.

    Args:
        artifact: Output of :func:`load_recognition_checkpoint`.
        frame: 5-minute OHLCV with ``time`` or ``timestamp``.

    Returns:
        Market state, structure tag, last-bar geometry, and the rule card
        for that bar. ``orders_enabled`` is false.

    Raises:
        ValueError: If the frame cannot form one finite 48-bar window.
    """
    import torch

    bars = resample_completed_15m(dedupe_timestamps(_as_ohlcv(frame)))
    features = add_engineered_features(bars)
    prepared = _label_frame(features)
    ends = eligible_ends(len(features), first_finite_bar(features))
    if ends.size == 0:
        raise ValueError("not enough completed 15-minute bars for recognition")
    end = int(ends[-1])
    window = stack_windows(prepared, np.asarray([end]), "engineered")
    scaled = _scale(window["features"], artifact["scaler_mean"], artifact["scaler_std"])
    model = artifact["model"]
    with torch.no_grad():
        geometry, state, tag = model(_as_tensor(scaled))
    geometry_prob = 1.0 / (1.0 + np.exp(-_to_numpy(geometry[0, -1])))
    state_prob = _softmax(_to_numpy(state[0]))
    tag_prob = _softmax(_to_numpy(tag[0]))
    state_index = int(np.argmax(state_prob))
    tag_index = int(np.argmax(tag_prob))
    active = [
        {
            "geometric_class": GEOMETRIC_CLASSES[index],
            "probability": float(geometry_prob[index]),
        }
        for index in range(len(GEOMETRIC_CLASSES))
        if float(geometry_prob[index]) >= 0.5
    ]
    return {
        "decision_path": RECOGNITION_DECISION_PATH,
        "orders_enabled": False,
        "spec_version": artifact["spec_version"],
        "bar_time": str(features["time"].iloc[end]),
        "market_state": MARKET_STATES[state_index],
        "market_state_probability": float(state_prob[state_index]),
        "structure_tag": STRUCTURE_TAGS[tag_index],
        "structure_tag_probability": float(tag_prob[tag_index]),
        "geometry": active,
        "rule_card": _rule_rows(prepared["rule_card"], end),
        "checkpoint": artifact["path"],
    }


def _as_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Require the research candle schema."""
    out = frame.copy()
    if "time" not in out.columns:
        if "timestamp" not in out.columns:
            raise ValueError("recognition frame needs time or timestamp")
        out["time"] = out["timestamp"]
    missing = [column for column in _OHLCV if column not in out.columns]
    if missing:
        raise ValueError(f"recognition frame is missing columns: {missing}")
    return out.loc[:, ["time", *_OHLCV]]


def _label_frame(features: pd.DataFrame) -> dict[str, object]:
    """Build the tensors ``stack_windows`` reads. Splits are not used."""
    open_ = features["open"].to_numpy(dtype=np.float64)
    high = features["high"].to_numpy(dtype=np.float64)
    low = features["low"].to_numpy(dtype=np.float64)
    close = features["close"].to_numpy(dtype=np.float64)
    atr = features["atr"].to_numpy(dtype=np.float64)
    geometry = geometry_matrix(open_, high, low, close, atr)
    states, tags = market_labels(high, low, close, atr)
    return {
        "features": features,
        "geometry": geometry,
        "states": states,
        "tags": tags,
        "rule_card": build_rule_card(features, atr, geometry),
    }


def _scale(windows: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """Apply the training scaler saved in the checkpoint."""
    scale = np.where(std < 1e-6, np.float32(1.0), std).astype(np.float32)
    return ((windows - mean.astype(np.float32)) / scale).astype(np.float32)


def _softmax(values: np.ndarray) -> np.ndarray:
    """Stable softmax over one logit vector."""
    shifted = values - float(np.max(values))
    exp = np.exp(shifted)
    total = float(exp.sum())
    if total <= 0.0:
        return np.full(values.shape, 1.0 / len(values))
    return exp / total


def _rule_rows(card: object, end: int) -> list[dict[str, Any]]:
    """Rule-card names for the scored bar. These are not model classes."""
    if not isinstance(card, pd.DataFrame) or card.empty:
        return []
    rows = card[card["bar_index"] == end]
    records: list[dict[str, Any]] = []
    for row in rows.to_dict(orient="records"):
        records.append(
            {
                "geometric_class": str(row.get("geometric_class")),
                "conventional_name": str(row.get("conventional_name")),
                "directional_bias": str(row.get("directional_bias")),
                "context": str(row.get("context")),
                "abstain": bool(row.get("abstain")),
            }
        )
    return records
