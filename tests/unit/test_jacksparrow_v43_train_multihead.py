"""Unit tests for v43 multi-head training helpers and export gates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.jacksparrow_v43_multihead import (
    V43_MIN_META_AUC_BY_HORIZON,
    validate_multihead_export_gates,
)
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
