"""Canonical v43 training contract (JackSparrow notebook ↔ agent parity).

Feature order must match exported ``metadata_v*.json`` ``features`` array and
notebook ``FEATURE_COLS_V25``. Default label horizon: 6×5m bars (~30m simple return).

Train/serve map: see ``docs/feature_entrypoints_audit.md``.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from feature_store.jacksparrow_v43_horizon import (
    V43_FORWARD_TARGET_BARS_DEFAULT,
    resolve_training_forward_bars,
)
from feature_store.jacksparrow_v43_multihead import (
    V43_MULTIHEAD_MODEL_FAMILY,
    validate_v43_multihead_metadata,
    validate_multihead_export_gates,
    resolve_min_meta_auc_by_horizon,
    V43_MIN_META_AUC_BY_HORIZON,
)

# Bump when ``V43_CANONICAL_FEATURES`` or semantics change (retrain + re-export metadata).
V43_COMPATIBLE_FEATURE_VERSION = "jacksparrow_v43_features_v1"

# Forward return label in training: close[t+h]/close[t] - 1 on 5m bars (new exports).
V43_FORWARD_TARGET_BARS = V43_FORWARD_TARGET_BARS_DEFAULT

# Ordered list — do not reorder without retraining and re-exporting metadata
V43_CANONICAL_FEATURES: tuple[str, ...] = (
    "ret_1",
    "ret_6",
    "ret_24",
    "mom_accel",
    "ema_21_50_cross",
    "price_ema21",
    "price_ema100",
    "rsi_14",
    "rsi_mom",
    "macd_hist_n",
    "bb_width",
    "bb_pos",
    "atr_pct",
    "vol_regime",
    "adx_14",
    "di_spread",
    "kauf_er_20",
    "obv_ret",
    "cmf_20",
    "session_vwap_dev",
    "body",
    "body_dir",
    "wick_asym",
    "sr_compression",
    "hour_sin",
    "hour_cos",
    "hurst_60",
    "trend_mom",
    "trend_conf",
    "funding_zscore",
    "funding_mom",
    "h_ret_1",
    "h_trend",
    "h_trend_200",
    "h_rsi_14",
    "h1_trend",
    "h1_rsi_14",
    "h1_adx",
    "h1_vol_regime",
    "bull_bar",
)

V43_EXPECTED_FEATURE_COUNT = len(V43_CANONICAL_FEATURES)


def validate_v43_metadata_compatibility(meta: Mapping[str, Any]) -> None:
    """Reject loads when feature list or optional ``compatible_feature_version`` disagrees with agent.

    Args:
        meta: Parsed ``metadata_v*.json`` for a JackSparrow v43 bundle.

    Raises:
        ValueError: On missing features, order mismatch, or incompatible version tag.
    """
    feats = meta.get("features")
    if not isinstance(feats, list) or not feats:
        raise ValueError("v43 metadata missing non-empty features list")
    ordered = tuple(str(x) for x in feats)
    if ordered != V43_CANONICAL_FEATURES:
        raise ValueError(
            "v43 metadata features[] does not match V43_CANONICAL_FEATURES "
            "(train-serve order-sensitive contract)"
        )
    ver = meta.get("compatible_feature_version")
    if ver is not None and isinstance(ver, str) and ver.strip():
        if str(ver).strip() != V43_COMPATIBLE_FEATURE_VERSION:
            raise ValueError(
                f"v43 metadata compatible_feature_version={ver!r} incompatible with "
                f"agent {V43_COMPATIBLE_FEATURE_VERSION!r}; re-export metadata or align contract"
            )
    family = str(meta.get("model_family") or "").strip()
    if family == V43_MULTIHEAD_MODEL_FAMILY or isinstance(meta.get("horizons"), dict):
        validate_v43_multihead_metadata(meta)
    else:
        raise ValueError(
            "v43 bundle must be multi-head (model_family=jacksparrow_v43_multihead, "
            "horizons{} with scalp_10m/intraday_30m/trend_1h/swing_2h). "
            "Legacy single-horizon (training_forward_bars=120) bundles are removed."
        )


def audit_v43_metadata_promotion(meta: Mapping[str, Any]) -> List[str]:
    """Return promotion warnings for meta-calibrator bundles (empty if OK)."""
    warnings: List[str] = []
    family = str(meta.get("model_family") or "").strip()
    horizons = meta.get("horizons")
    if family == "jacksparrow_v43_multihead" or isinstance(horizons, dict):
        for key, min_auc in resolve_min_meta_auc_by_horizon().items():
            block = horizons.get(key) if isinstance(horizons, dict) else None
            if not isinstance(block, dict):
                warnings.append(f"horizons[{key}] missing for promotion audit")
                continue
            vm = block.get("validation_metrics")
            if not isinstance(vm, dict):
                warnings.append(f"horizons[{key}] missing validation_metrics")
                continue
            meta_auc = vm.get("meta_auc")
            if meta_auc is not None:
                try:
                    auc = float(meta_auc)
                    if auc < min_auc:
                        warnings.append(
                            f"horizons[{key}] meta_auc={auc:.4f} below minimum {min_auc:.2f}"
                        )
                except (TypeError, ValueError):
                    pass
            short_cands = vm.get("short_candidates")
            if isinstance(short_cands, dict):
                try:
                    sc = int(short_cands.get("count") or 0)
                except (TypeError, ValueError):
                    sc = 0
                if sc == 0:
                    warnings.append(
                        f"horizons[{key}] short_candidates.count=0 on validation"
                    )
        return warnings

    vm = meta.get("validation_metrics")
    if not isinstance(vm, dict):
        return warnings

    inference_path = str(vm.get("inference_path") or "").strip()
    if inference_path == "meta_calibrator":
        meta_auc = vm.get("meta_auc")
        if meta_auc is not None:
            try:
                min_auc = V43_MIN_META_AUC_BY_HORIZON.get("intraday_30m", 0.56)
                if float(meta_auc) < min_auc:
                    warnings.append(
                        f"meta_auc={float(meta_auc):.4f} below minimum {min_auc:.2f}"
                    )
            except (TypeError, ValueError):
                pass
        short_cands = vm.get("short_candidates")
        if isinstance(short_cands, dict):
            try:
                sc = int(short_cands.get("count") or 0)
            except (TypeError, ValueError):
                sc = 0
            if sc == 0:
                warnings.append(
                    "short_candidates.count=0 on validation (meta-stack may never fire shorts)"
                )
        arch = meta.get("model_architecture")
        if isinstance(arch, dict) and arch.get("meta_learner"):
            if not arch.get("calibrator"):
                warnings.append(
                    "model_architecture has meta_learner but no calibrator "
                    "(gate-5 scale mismatch risk)"
                )

    return warnings


def validate_v43_metadata_promotion(
    meta: Mapping[str, Any],
    *,
    strict: bool = False,
) -> List[str]:
    """Run promotion audit; raise when ``strict`` and warnings exist."""
    warnings = audit_v43_metadata_promotion(meta)
    family = str(meta.get("model_family") or "").strip()
    is_multihead = isinstance(meta.get("horizons"), dict) or family == "jacksparrow_v43_multihead"
    if is_multihead:
        gate_failures = validate_multihead_export_gates(meta, strict=False)
        warnings.extend(gate_failures)
        if strict and gate_failures:
            raise ValueError(
                "v43 metadata failed promotion gate: " + "; ".join(gate_failures)
            )
    elif strict and warnings:
        raise ValueError(
            "v43 metadata failed promotion gate: " + "; ".join(warnings)
        )
    return warnings
