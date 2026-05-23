"""JackSparrow v43 multi-head intraday contract (2/6/12/24 bars on 5m grid)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from feature_store.jacksparrow_v43_horizon import (
    V43_CANDLE_MINUTES,
    forward_bars_to_minutes,
    horizon_profile,
)

V43_MULTIHEAD_MODEL_FAMILY = "jacksparrow_v43_multihead"
V43_MULTIHEAD_ARTIFACT_FORMAT = "jacksparrow_v43_multihead_v1"

# Canonical horizon keys (stable in metadata + artifact).
V43_HORIZON_KEYS: Tuple[str, ...] = (
    "scalp_10m",
    "intraday_30m",
    "trend_1h",
    "swing_2h",
)

V43_HORIZON_KEY_TO_BARS: Dict[str, int] = {
    "scalp_10m": 2,
    "intraday_30m": 6,
    "trend_1h": 12,
    "swing_2h": 24,
}

V43_MULTIHEAD_BARS: Tuple[int, ...] = tuple(sorted(set(V43_HORIZON_KEY_TO_BARS.values())))

# Minimum meta-classifier AUC on validation for production export (BTC intraday).
V43_MIN_META_AUC_BY_HORIZON: Dict[str, float] = {
    "scalp_10m": 0.54,
    "intraday_30m": 0.56,
    "trend_1h": 0.58,
    "swing_2h": 0.60,
}

# Minimum validation correlation (predicted vs realized forward return).
V43_MIN_VALIDATION_CORR_BY_HORIZON: Dict[str, float] = {
    "scalp_10m": 0.0,
    "intraday_30m": 0.0,
    "trend_1h": 0.0,
    "swing_2h": 0.0,
}

# Policy: which ML heads confirm / veto for a thesis target horizon.
V43_THESIS_CONFIRMATION_HEADS: Dict[int, Tuple[int, ...]] = {
    2: (2, 6),
    6: (6, 12),
    12: (12, 24),
    24: (24,),
}

V43_THESIS_OPPOSITION_HEADS: Dict[int, int] = {
    2: 12,
    6: 24,
    12: 24,
    24: 24,
}


def bars_to_horizon_key(forward_bars: int) -> str:
    for key, bars in V43_HORIZON_KEY_TO_BARS.items():
        if int(bars) == int(forward_bars):
            return key
    raise ValueError(f"unsupported forward_bars={forward_bars}")


def horizon_key_to_bars(key: str) -> int:
    k = str(key or "").strip()
    if k not in V43_HORIZON_KEY_TO_BARS:
        raise ValueError(f"unknown horizon key={key!r}")
    return int(V43_HORIZON_KEY_TO_BARS[k])


def required_horizon_keys() -> Tuple[str, ...]:
    return V43_HORIZON_KEYS


def validate_v43_multihead_metadata(meta: Mapping[str, Any]) -> None:
    """Require multi-head horizons block; reject legacy single-horizon-only bundles."""
    family = str(meta.get("model_family") or "").strip()
    if family and family != V43_MULTIHEAD_MODEL_FAMILY:
        raise ValueError(
            f"v43 metadata model_family={family!r} expected {V43_MULTIHEAD_MODEL_FAMILY!r}"
        )
    horizons = meta.get("horizons")
    if not isinstance(horizons, dict) or not horizons:
        raise ValueError(
            "v43 multi-head metadata missing non-empty horizons{} "
            "(retrain with jacksparrow_v43_multihead export)"
        )
    for key in V43_HORIZON_KEYS:
        block = horizons.get(key)
        if not isinstance(block, dict):
            raise ValueError(f"v43 horizons missing block for {key!r}")
        try:
            fb = int(block.get("forward_bars"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"horizons[{key!r}].forward_bars invalid") from exc
        if fb != V43_HORIZON_KEY_TO_BARS[key]:
            raise ValueError(
                f"horizons[{key!r}].forward_bars={fb} != expected {V43_HORIZON_KEY_TO_BARS[key]}"
            )
        vm = block.get("validation_metrics")
        if not isinstance(vm, dict):
            raise ValueError(f"horizons[{key!r}] missing validation_metrics")
        if vm.get("dynamic_threshold") is None:
            raise ValueError(f"horizons[{key!r}] missing dynamic_threshold in validation_metrics")
    feats = meta.get("features")
    if isinstance(feats, list) and feats:
        from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES

        ordered = tuple(str(x) for x in feats)
        if ordered != V43_CANONICAL_FEATURES:
            raise ValueError("v43 metadata features[] order mismatch vs V43_CANONICAL_FEATURES")
    # Legacy 120-bar-only bundles are not supported.
    legacy = meta.get("training_forward_bars")
    if legacy is not None:
        try:
            if int(legacy) == 120 and not isinstance(meta.get("horizons"), dict):
                raise ValueError("legacy 120-bar single-horizon bundle is no longer supported")
        except (TypeError, ValueError):
            pass


def parse_horizons_from_metadata(meta: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    validate_v43_multihead_metadata(meta)
    horizons = meta.get("horizons")
    assert isinstance(horizons, dict)
    out: Dict[str, Dict[str, Any]] = {}
    for key in V43_HORIZON_KEYS:
        block = dict(horizons.get(key) or {})
        fb = int(block.get("forward_bars", V43_HORIZON_KEY_TO_BARS[key]))
        prof = horizon_profile(fb)
        block.setdefault("horizon_minutes", forward_bars_to_minutes(fb))
        block.setdefault("horizon_label", prof.label)
        out[key] = block
    return out


def primary_execution_horizon_bars(meta: Mapping[str, Any]) -> int:
    raw = meta.get("primary_execution_horizon_bars")
    if raw is not None:
        try:
            bars = int(raw)
            if bars in V43_MULTIHEAD_BARS:
                return bars
        except (TypeError, ValueError):
            pass
    return 6


def validate_multihead_export_gates(
    meta: Mapping[str, Any],
    *,
    strict: bool = True,
) -> List[str]:
    """Return export gate failures; raise when ``strict`` and any check fails."""
    failures: List[str] = []
    horizons = meta.get("horizons")
    if not isinstance(horizons, dict):
        failures.append("metadata missing horizons dict")
        if strict:
            raise ValueError("v43 export gates failed: " + "; ".join(failures))
        return failures

    for key in V43_HORIZON_KEYS:
        block = horizons.get(key)
        if not isinstance(block, dict):
            failures.append(f"horizons[{key}] missing")
            continue
        vm = block.get("validation_metrics")
        if not isinstance(vm, dict):
            failures.append(f"horizons[{key}] missing validation_metrics")
            continue
        if vm.get("inference_path") != "meta_calibrator":
            failures.append(f"horizons[{key}] inference_path must be meta_calibrator")

        try:
            auc = float(vm.get("meta_auc"))
        except (TypeError, ValueError):
            auc = None
        min_auc = V43_MIN_META_AUC_BY_HORIZON.get(key, 0.54)
        if auc is None:
            failures.append(f"horizons[{key}] missing meta_auc")
        elif auc < min_auc:
            failures.append(
                f"horizons[{key}] meta_auc={auc:.4f} < minimum {min_auc:.2f}"
            )

        try:
            corr = float(vm.get("validation_corr"))
        except (TypeError, ValueError):
            corr = None
        min_corr = V43_MIN_VALIDATION_CORR_BY_HORIZON.get(key, 0.0)
        if corr is None:
            failures.append(f"horizons[{key}] missing validation_corr")
        elif corr < min_corr:
            failures.append(
                f"horizons[{key}] validation_corr={corr:.4f} < minimum {min_corr:.2f}"
            )

        tradable = vm.get("tradable_label_fraction")
        if tradable is not None:
            try:
                if float(tradable) < 0.05:
                    failures.append(
                        f"horizons[{key}] tradable_label_fraction={float(tradable):.4f} too low"
                    )
            except (TypeError, ValueError):
                pass

    if strict and failures:
        raise ValueError("v43 multi-head export gates failed: " + "; ".join(failures))
    return failures


def head_thresholds(meta: Mapping[str, Any], horizon_key: str) -> Tuple[float, float]:
    block = parse_horizons_from_metadata(meta).get(horizon_key, {})
    vm = block.get("validation_metrics") if isinstance(block.get("validation_metrics"), dict) else block
    dt = float(vm.get("dynamic_threshold", block.get("dynamic_threshold", 0.005)) or 0.005)
    st = vm.get("short_threshold", block.get("short_threshold"))
    short_mag = abs(float(st)) if st is not None else dt
    return dt, short_mag
