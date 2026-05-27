"""JackSparrow v43 multi-head intraday contract (2/6/12/24 bars on 5m grid)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
# Primary head (30m execution) uses the tightest bar; 1h/2h are advisory unless full strict.
V43_MIN_META_AUC_BY_HORIZON: Dict[str, float] = {
    "scalp_10m": 0.53,  # execution head — aligned with intraday_30m production min
    "intraday_30m": 0.53,
    "trend_1h": 0.58,
    "swing_2h": 0.60,
}

# Full strict export applies production mins to these horizons only (Colab default).
V43_EXPORT_PRIMARY_ONLY_HORIZON_KEYS: Tuple[str, ...] = ("scalp_10m", "intraday_30m")

# Minimum validation correlation (predicted vs realized forward return).
V43_MIN_VALIDATION_CORR_BY_HORIZON: Dict[str, float] = {
    "scalp_10m": 0.08,  # execution head — must clear its own corr floor
    "intraday_30m": 0.0,
    "trend_1h": 0.0,
    "swing_2h": 0.0,
}

# Always block export when meta_auc falls below this on primary horizons.
V43_EXPORT_HARD_FLOOR_META_AUC: float = 0.52

# Secondary horizons (1h/2h) in primary-only export mode: block below this only.
V43_EXPORT_SECONDARY_HARD_FLOOR_META_AUC: float = 0.50

_ENV_MIN_AUC_KEYS: Dict[str, str] = {
    "scalp_10m": "V43_MIN_META_AUC_SCALP_10M",
    "intraday_30m": "V43_MIN_META_AUC_INTRADAY_30M",
    "trend_1h": "V43_MIN_META_AUC_TREND_1H",
    "swing_2h": "V43_MIN_META_AUC_SWING_2H",
}

_ENV_MIN_CORR_KEYS: Dict[str, str] = {
    "scalp_10m": "V43_MIN_VALIDATION_CORR_SCALP_10M",
    "intraday_30m": "V43_MIN_VALIDATION_CORR_INTRADAY_30M",
    "trend_1h": "V43_MIN_VALIDATION_CORR_TREND_1H",
    "swing_2h": "V43_MIN_VALIDATION_CORR_SWING_2H",
}


def resolve_min_meta_auc_by_horizon() -> Dict[str, float]:
    """Production minimums with optional per-horizon env overrides."""
    out = dict(V43_MIN_META_AUC_BY_HORIZON)
    for key, env_name in _ENV_MIN_AUC_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            pass
    return out


def resolve_min_validation_corr_by_horizon() -> Dict[str, float]:
    """Production corr minimums with optional per-horizon env overrides."""
    out = dict(V43_MIN_VALIDATION_CORR_BY_HORIZON)
    for key, env_name in _ENV_MIN_CORR_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            pass
    return out


def resolve_export_hard_floor_meta_auc() -> float:
    raw = os.environ.get("V43_EXPORT_HARD_FLOOR_META_AUC")
    if raw is None or str(raw).strip() == "":
        return V43_EXPORT_HARD_FLOOR_META_AUC
    try:
        return float(raw)
    except (TypeError, ValueError):
        return V43_EXPORT_HARD_FLOOR_META_AUC


def resolve_export_secondary_hard_floor_meta_auc() -> float:
    raw = os.environ.get("V43_EXPORT_SECONDARY_HARD_FLOOR_META_AUC")
    if raw is None or str(raw).strip() == "":
        return V43_EXPORT_SECONDARY_HARD_FLOOR_META_AUC
    try:
        return float(raw)
    except (TypeError, ValueError):
        return V43_EXPORT_SECONDARY_HARD_FLOOR_META_AUC


def resolve_export_strict_primary_only() -> bool:
    raw = os.environ.get("V43_EXPORT_STRICT_PRIMARY_ONLY")
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() in ("1", "true", "yes")

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
        from feature_store.jacksparrow_v43_contract import resolve_v43_feature_contract

        try:
            _ver, expected = resolve_v43_feature_contract(meta)
        except ValueError as exc:
            raise ValueError(
                "v43 metadata features[] order mismatch vs supported feature contract"
            ) from exc
        ordered = tuple(str(x) for x in feats)
        if ordered != expected:
            raise ValueError(
                "v43 metadata features[] order mismatch vs supported feature contract"
            )
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
    if raw is None:
        raise ValueError(
            "metadata missing primary_execution_horizon_bars — "
            "re-export bundle from Cell 25 before deploying."
        )
    try:
        bars = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"primary_execution_horizon_bars={raw!r} is not a valid integer"
        ) from exc
    if bars not in V43_MULTIHEAD_BARS:
        raise ValueError(
            f"primary_execution_horizon_bars={bars} not in {V43_MULTIHEAD_BARS}"
        )
    return bars


def validate_multihead_export_gates(
    meta: Mapping[str, Any],
    *,
    strict: bool = True,
    return_soft: bool = False,
    horizon_keys: Optional[Tuple[str, ...]] = None,
    strict_primary_only: Optional[bool] = None,
) -> List[str] | Tuple[List[str], List[str]]:
    """Return export gate failures; raise when ``strict`` and any hard failure exists.

    When ``strict`` is False, heads between the hard floor and the production minimum
    are reported as *soft* failures (warnings) but do not block.

    When ``strict_primary_only`` is True (default via env), production minimums apply
    only to ``V43_EXPORT_PRIMARY_ONLY_HORIZON_KEYS`` (scalp + intraday_30m). Longer
    horizons must only clear the secondary hard floor (default 0.50).
    """
    failures: List[str] = []
    soft_failures: List[str] = []
    min_auc_by_key = resolve_min_meta_auc_by_horizon()
    hard_floor = resolve_export_hard_floor_meta_auc()
    secondary_floor = resolve_export_secondary_hard_floor_meta_auc()
    primary_only = (
        resolve_export_strict_primary_only()
        if strict_primary_only is None
        else bool(strict_primary_only)
    )
    primary_keys = frozenset(V43_EXPORT_PRIMARY_ONLY_HORIZON_KEYS)
    keys = horizon_keys or V43_HORIZON_KEYS
    horizons = meta.get("horizons")
    if not isinstance(horizons, dict):
        failures.append("metadata missing horizons dict")
        if strict and failures and not return_soft:
            raise ValueError("v43 export gates failed: " + "; ".join(failures))
        return (failures, soft_failures) if return_soft else failures

    for key in keys:
        block = horizons.get(key)
        if not isinstance(block, dict):
            failures.append(f"horizons[{key}] missing")
            continue
        vm = block.get("validation_metrics")
        if not isinstance(vm, dict):
            failures.append(f"horizons[{key}] missing validation_metrics")
            continue
        inf_path = str(vm.get("inference_path") or "").strip()
        if inf_path not in ("meta_calibrator", "regressor_mean"):
            failures.append(
                f"horizons[{key}] inference_path must be meta_calibrator or regressor_mean"
            )

        if inf_path == "meta_calibrator":
            try:
                auc = float(vm.get("meta_auc"))
            except (TypeError, ValueError):
                auc = None
            min_auc = min_auc_by_key.get(key, 0.54)
            is_primary = key in primary_keys
            floor = hard_floor if (not primary_only or is_primary) else secondary_floor
            if auc is None:
                failures.append(f"horizons[{key}] missing meta_auc")
            elif auc < floor:
                failures.append(
                    f"horizons[{key}] meta_auc={auc:.4f} < hard floor {floor:.2f} "
                    "(at or below random — retrain before export)"
                )
            elif auc < min_auc:
                msg = f"horizons[{key}] meta_auc={auc:.4f} < minimum {min_auc:.2f}"
                enforce_min = strict and (not primary_only or is_primary)
                if enforce_min:
                    failures.append(msg)
                else:
                    soft_failures.append(msg)

        try:
            corr = float(vm.get("validation_corr"))
        except (TypeError, ValueError):
            corr = None
        min_corr = resolve_min_validation_corr_by_horizon().get(key, 0.0)
        if corr is None:
            failures.append(f"horizons[{key}] missing validation_corr")
        elif corr < min_corr:
            msg = f"horizons[{key}] validation_corr={corr:.4f} < minimum {min_corr:.2f}"
            # Hard-block only clearly negative corr; tiny negatives are warnings when return_soft.
            if corr is not None and corr < -0.02:
                failures.append(msg)
            elif strict and not return_soft:
                failures.append(msg)
            else:
                soft_failures.append(msg)

        tradable = vm.get("tradable_label_fraction")
        if tradable is not None:
            try:
                if float(tradable) < 0.05:
                    msg = (
                        f"horizons[{key}] tradable_label_fraction="
                        f"{float(tradable):.4f} too low"
                    )
                    if strict:
                        failures.append(msg)
                    else:
                        soft_failures.append(msg)
            except (TypeError, ValueError):
                pass

    if strict and failures and not return_soft:
        raise ValueError("v43 multi-head export gates failed: " + "; ".join(failures))
    if return_soft:
        return failures, soft_failures
    return failures


def format_horizon_training_diagnostics(meta: Mapping[str, Any]) -> str:
    """Per-head rows, label modes, tradable fractions, and validation metrics."""
    horizons = meta.get("horizons") if isinstance(meta.get("horizons"), dict) else {}
    cost = meta.get("runtime_cost_assumptions") if isinstance(meta.get("runtime_cost_assumptions"), dict) else {}
    lines = [
        "Horizon training diagnostics",
        f"target_definition={meta.get('target_definition')} "
        f"round_trip_cost_pct={cost.get('round_trip_cost_pct')}",
        f"{'horizon':<16} {'bars':>4} {'rows_tr':>7} {'rows_val':>7} "
        f"{'tradable':>8} {'label_mode':<28} {'meta_auc':>8} {'corr':>8}",
        "-" * 95,
    ]
    for key in V43_HORIZON_KEYS:
        block = horizons.get(key) if isinstance(horizons, dict) else None
        if not isinstance(block, dict):
            lines.append(f"{key:<16} {'—':>4} {'—':>7} {'—':>7} {'—':>8} {'MISSING':<28} {'—':>8} {'—':>8}")
            continue
        split = block.get("split") if isinstance(block.get("split"), dict) else {}
        stats = block.get("label_stats") if isinstance(block.get("label_stats"), dict) else {}
        vm = block.get("validation_metrics") if isinstance(block.get("validation_metrics"), dict) else {}
        try:
            tradable = float(stats.get("tradable_label_fraction"))
            trad_s = f"{tradable:.3f}"
        except (TypeError, ValueError):
            trad_s = "n/a"
        try:
            auc_s = f"{float(vm.get('meta_auc')):.4f}"
        except (TypeError, ValueError):
            auc_s = "n/a"
        try:
            corr_s = f"{float(vm.get('validation_corr')):.4f}"
        except (TypeError, ValueError):
            corr_s = "n/a"
        label_mode = str(block.get("label_mode") or vm.get("label_mode") or "—")[:28]
        lines.append(
            f"{key:<16} {int(block.get('forward_bars', 0)):>4} "
            f"{int(split.get('rows_train', 0)):>7} "
            f"{int(split.get('rows_validation', 0)):>7} "
            f"{trad_s:>8} {label_mode:<28} {auc_s:>8} {corr_s:>8}"
        )
    lines.append("")
    lines.append(format_export_gate_summary(meta))
    return "\n".join(lines)


def format_export_gate_summary(
    meta: Mapping[str, Any],
    *,
    strict_primary_only: Optional[bool] = None,
) -> str:
    """Human-readable per-horizon meta_auc vs thresholds."""
    min_auc_by_key = resolve_min_meta_auc_by_horizon()
    hard_floor = resolve_export_hard_floor_meta_auc()
    secondary_floor = resolve_export_secondary_hard_floor_meta_auc()
    primary_only = (
        resolve_export_strict_primary_only()
        if strict_primary_only is None
        else bool(strict_primary_only)
    )
    primary_keys = frozenset(V43_EXPORT_PRIMARY_ONLY_HORIZON_KEYS)
    horizons = meta.get("horizons") if isinstance(meta.get("horizons"), dict) else {}
    lines = [
        f"{'horizon':<16} {'meta_auc':>8} {'min':>6} {'floor':>6} {'status':>8}",
        "-" * 50,
    ]
    for key in V43_HORIZON_KEYS:
        block = horizons.get(key) if isinstance(horizons, dict) else None
        vm = block.get("validation_metrics") if isinstance(block, dict) else {}
        try:
            auc = float(vm.get("meta_auc"))
            auc_s = f"{auc:.4f}"
        except (TypeError, ValueError):
            auc = None
            auc_s = "n/a"
        min_auc = min_auc_by_key.get(key, 0.54)
        is_primary = key in primary_keys
        floor = hard_floor if (not primary_only or is_primary) else secondary_floor
        if auc is None:
            status = "MISSING"
        elif auc < floor:
            status = "BLOCK"
        elif primary_only and not is_primary and auc < min_auc:
            status = "SOFT"
        elif auc < min_auc:
            status = "WARN"
        else:
            status = "PASS"
        lines.append(
            f"{key:<16} {auc_s:>8} {min_auc:>6.2f} {hard_floor:>6.2f} {status:>8}"
        )
    return "\n".join(lines)


def head_thresholds(meta: Mapping[str, Any], horizon_key: str) -> Tuple[float, float]:
    block = parse_horizons_from_metadata(meta).get(horizon_key, {})
    vm = block.get("validation_metrics") if isinstance(block.get("validation_metrics"), dict) else block
    dt = float(vm.get("dynamic_threshold", block.get("dynamic_threshold", 0.005)) or 0.005)
    st = vm.get("short_threshold", block.get("short_threshold"))
    short_mag = abs(float(st)) if st is not None else dt
    return dt, short_mag
