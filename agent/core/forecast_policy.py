"""Live 30-minute forecast policy: class map, 12-hour lock, ATR brackets."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research.forecast_30m.contract_v5 import (
    FORECAST_BUNDLE_DIR_NAME,
    FORECAST_DECISION_PATH,
    FORECAST_SL_ATR_MULT,
    FORECAST_TP_ATR_MULT,
    HORIZON_MINUTES,
    SIGNAL_BY_CLASS,
)
from research.forecast_30m.inference import map_direction_signal

_FUSION_DECISION_PATH = "mtf_fusion"
_ENTRY = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_LAST_ENTRY: Dict[str, datetime] = {}


def forecast_bundle_dir(model_dir: Path | str) -> Path:
    """Return the live forecast bundle directory under ``MODEL_DIR``."""
    return Path(model_dir) / FORECAST_BUNDLE_DIR_NAME


def promoted_forecast_bundle(model_dir: Path | str) -> Path | None:
    """Return the bundle path when it is approved for live orders."""
    bundle = forecast_bundle_dir(model_dir)
    manifest_path = bundle / "manifest.json"
    models_path = bundle / "models.joblib"
    if not manifest_path.is_file() or not models_path.is_file():
        return None
    import json

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not bool(manifest.get("orders_enabled")):
        return None
    return bundle


def resolve_transformer_decision_path(model_dir: Path | str) -> str:
    """Honor an explicit env path; otherwise promote a passing forecast bundle.

    ``TRANSFORMER_DECISION_PATH=mtf_fusion`` stays the rollback. When the
    environment variable is unset and a promoted bundle is on disk, the live
    path becomes ``forecast_30m``.
    """
    explicit = (os.getenv("TRANSFORMER_DECISION_PATH") or "").strip()
    if explicit:
        return explicit
    from agent.core.config import settings

    configured = str(
        getattr(settings, "transformer_decision_path", _FUSION_DECISION_PATH)
        or _FUSION_DECISION_PATH
    ).strip()
    if configured != _FUSION_DECISION_PATH:
        return configured
    if promoted_forecast_bundle(model_dir) is not None:
        return FORECAST_DECISION_PATH
    return configured or _FUSION_DECISION_PATH


def map_forecast_signal(
    direction: str | None,
    probability: float | None,
    floor: float | None,
) -> Tuple[str, List[str]]:
    """Return the wire signal and reason codes for one forecast."""
    signal = map_direction_signal(direction, probability, floor)
    reasons: List[str] = []
    if signal == "HOLD":
        if direction is None:
            reasons.append("forecast_no_direction")
        elif direction == "NEUTRAL":
            reasons.append("forecast_neutral")
        else:
            reasons.append("forecast_below_probability_floor")
    else:
        reasons.append(f"forecast_{SIGNAL_BY_CLASS.get(direction or '', signal).lower()}")
    return signal, reasons


def apply_horizon_lock(
    signal: str,
    *,
    symbol: str,
    now: datetime,
    last_entry: datetime | None = None,
    horizon_minutes: int = HORIZON_MINUTES,
) -> Tuple[str, List[str]]:
    """Skip a new entry while a 12-hour forecast position is still reserved."""
    if signal not in _ENTRY:
        return signal, []
    previous = last_entry if last_entry is not None else _LAST_ENTRY.get(symbol)
    if previous is None:
        return signal, []
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    if current < previous + timedelta(minutes=int(horizon_minutes)):
        return "HOLD", ["forecast_horizon_busy"]
    return signal, []


def remember_forecast_entry(symbol: str, when: datetime) -> None:
    """Record a live forecast entry so later bars stay locked."""
    stamp = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    _LAST_ENTRY[symbol] = stamp


def clear_forecast_entries() -> None:
    """Drop in-memory horizon locks. Used by tests."""
    _LAST_ENTRY.clear()


def last_forecast_entry(symbol: str) -> Optional[datetime]:
    """Return the last recorded forecast entry time for ``symbol``."""
    return _LAST_ENTRY.get(symbol)


def build_forecast_execution_plan(
    *,
    signal: str,
    confidence: float,
    size_fraction: float,
    reason_codes: List[str],
) -> Dict[str, Any]:
    """ATR-scaled 12-hour brackets for a forecast entry."""
    if signal not in _ENTRY:
        return {}
    return {
        "signal": signal,
        "primary_tf": "30m",
        "duration_key": "h12h",
        "duration_minutes": HORIZON_MINUTES,
        "max_hold_minutes": HORIZON_MINUTES,
        "size_fraction": float(size_fraction),
        "size_scale": 1.0,
        "sl_tp_source": "atr",
        "sl_atr_mult": FORECAST_SL_ATR_MULT,
        "tp_atr_mult": FORECAST_TP_ATR_MULT,
        "reason_codes": list(reason_codes),
        "confidence": float(confidence),
    }
