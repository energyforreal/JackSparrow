"""Unit tests for v43 multi-head training helpers and export gates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.jacksparrow_v43_multihead import (
    V43_MIN_META_AUC_BY_HORIZON,
    format_horizon_training_diagnostics,
    validate_multihead_export_gates,
)
from feature_store.jacksparrow_v43_train_multihead import V43_HORIZON_COST_SCALE
from feature_store.jacksparrow_v43_train_multihead import (
    build_cost_aware_forward_labels,
    build_forward_labels,
)


def test_build_cost_aware_forward_labels_suppresses_sub_cost() -> None:
    close = pd.Series([100.0, 100.0, 100.0, 100.05, 100.0], index=range(5))
    raw = build_forward_labels(close, forward_bars=1)
    masked, stats = build_cost_aware_forward_labels(
        close, forward_bars=1, round_trip_cost=0.01
    )
    assert stats["sub_cost_suppressed_fraction"] >= 0.0
    assert pd.isna(masked.iloc[0])
    assert not pd.isna(raw.iloc[0])


def test_validate_multihead_export_gates_blocks_below_hard_floor() -> None:
    meta = {
        "horizons": {
            "scalp_10m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.51,
                    "validation_corr": 0.01,
                }
            },
            "intraday_30m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.57,
                    "validation_corr": 0.01,
                }
            },
            "trend_1h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.59,
                    "validation_corr": 0.01,
                }
            },
            "swing_2h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.61,
                    "validation_corr": 0.01,
                }
            },
        }
    }
    failures, soft = validate_multihead_export_gates(meta, strict=False, return_soft=True)
    assert any("scalp_10m" in f for f in failures)
    assert failures  # hard floor blocks


def test_validate_multihead_export_gates_soft_warns_near_miss() -> None:
    meta = {
        "horizons": {
            "scalp_10m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.55,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "intraday_30m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.525,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "trend_1h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.59,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "swing_2h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.61,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
        }
    }
    failures, soft = validate_multihead_export_gates(meta, strict=False, return_soft=True)
    assert not failures
    assert any("intraday_30m" in s for s in soft)


def test_validate_multihead_export_gates_blocks_low_auc() -> None:
    meta = {
        "horizons": {
            "scalp_10m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.50,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "intraday_30m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.57,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "trend_1h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.59,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
            "swing_2h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.61,
                    "validation_corr": 0.01,
                    "tradable_label_fraction": 0.2,
                }
            },
        }
    }
    failures = validate_multihead_export_gates(meta, strict=False)
    assert any("scalp_10m" in f for f in failures)
    assert not any("swing_2h" in f for f in failures)


def test_horizon_cost_scale_relaxes_longer_horizons() -> None:
    assert V43_HORIZON_COST_SCALE[12] < V43_HORIZON_COST_SCALE[6]
    assert V43_HORIZON_COST_SCALE[24] < V43_HORIZON_COST_SCALE[12]


def test_format_horizon_training_diagnostics_includes_heads() -> None:
    meta = {
        "target_definition": "cost_aware_forward_return",
        "runtime_cost_assumptions": {"round_trip_cost_pct": 0.0048},
        "horizons": {
            "intraday_30m": {
                "forward_bars": 6,
                "label_mode": "cost_aware",
                "label_stats": {"tradable_label_fraction": 0.35},
                "split": {"rows_train": 1000, "rows_validation": 200},
                "validation_metrics": {
                    "meta_auc": 0.57,
                    "validation_corr": 0.02,
                    "inference_path": "meta_calibrator",
                },
            },
        },
    }
    text = format_horizon_training_diagnostics(meta)
    assert "intraday_30m" in text
    assert "0.5700" in text or "0.57" in text


def test_validate_multihead_export_gates_user_colab_metrics_primary_only() -> None:
    """Regression: typical Colab run passes export with primary-only strict gates."""
    meta = {
        "horizons": {
            "scalp_10m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.6013,
                    "validation_corr": 0.01,
                }
            },
            "intraday_30m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.5387,
                    "validation_corr": 0.01,
                }
            },
            "trend_1h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.5072,
                    "validation_corr": -0.0055,
                }
            },
            "swing_2h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.5093,
                    "validation_corr": 0.01,
                }
            },
        }
    }
    failures, warnings = validate_multihead_export_gates(
        meta, strict=True, return_soft=True, strict_primary_only=True
    )
    assert failures == []
    assert warnings


def test_validate_multihead_export_gates_strict_with_return_soft_does_not_raise() -> None:
    meta = {
        "horizons": {
            "scalp_10m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.55,
                    "validation_corr": 0.01,
                }
            },
            "intraday_30m": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.55,
                    "validation_corr": 0.01,
                }
            },
            "trend_1h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.59,
                    "validation_corr": 0.01,
                }
            },
            "swing_2h": {
                "validation_metrics": {
                    "inference_path": "meta_calibrator",
                    "meta_auc": 0.61,
                    "validation_corr": 0.01,
                }
            },
        }
    }
    failures, soft = validate_multihead_export_gates(
        meta, strict=True, return_soft=True
    )
    assert isinstance(failures, list)
    assert isinstance(soft, list)


def test_validate_multihead_export_gates_passes_strong_model() -> None:
    horizons = {}
    for key, min_auc in V43_MIN_META_AUC_BY_HORIZON.items():
        horizons[key] = {
            "validation_metrics": {
                "inference_path": "meta_calibrator",
                "meta_auc": min_auc + 0.02,
                "validation_corr": 0.05,
                "tradable_label_fraction": 0.25,
            }
        }
    failures = validate_multihead_export_gates({"horizons": horizons}, strict=True)
    assert failures == []
