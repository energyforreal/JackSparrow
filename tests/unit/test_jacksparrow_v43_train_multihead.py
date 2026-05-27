"""Unit tests for v43 multi-head training helpers and export gates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from feature_store.jacksparrow_v43_multihead import (
    V43_MIN_META_AUC_BY_HORIZON,
    format_horizon_training_diagnostics,
    primary_execution_horizon_bars,
    validate_multihead_export_gates,
)
from feature_store.jacksparrow_v43_train_multihead import V43_HORIZON_COST_SCALE
from feature_store.jacksparrow_v43_train_multihead import (
    build_cost_aware_forward_labels,
    build_forward_labels,
    resolve_validation_threshold_percentiles,
)


def test_cost_aware_labels_more_tradable_at_runtime_cost() -> None:
    """Unleveraged training cost (~0.0016) yields more labels than legacy 0.0048."""
    rng = np.random.default_rng(42)
    n = 5000
    rets = rng.normal(0.0006, 0.0005, size=n)
    close = pd.Series(100.0 * np.cumprod(1.0 + rets))
    _, stats_legacy = build_cost_aware_forward_labels(
        close, forward_bars=6, round_trip_cost=0.0048
    )
    _, stats_runtime = build_cost_aware_forward_labels(
        close, forward_bars=6, round_trip_cost=0.0016
    )
    assert stats_runtime["tradable_label_fraction"] > stats_legacy["tradable_label_fraction"]


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
    assert V43_HORIZON_COST_SCALE[2] == V43_HORIZON_COST_SCALE[6]
    assert V43_HORIZON_COST_SCALE[12] < V43_HORIZON_COST_SCALE[6]
    assert V43_HORIZON_COST_SCALE[24] < V43_HORIZON_COST_SCALE[12]


def test_resolve_validation_threshold_percentiles_defaults_90_10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V43_THRESHOLD_PERCENTILE", raising=False)
    monkeypatch.delenv("V43_THRESHOLD_PERCENTILE_LONG", raising=False)
    monkeypatch.delenv("V43_THRESHOLD_PERCENTILE_SHORT", raising=False)
    assert resolve_validation_threshold_percentiles() == (90.0, 10.0)


def test_resolve_validation_threshold_percentiles_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V43_THRESHOLD_PERCENTILE_LONG", "85")
    monkeypatch.setenv("V43_THRESHOLD_PERCENTILE_SHORT", "15")
    assert resolve_validation_threshold_percentiles() == (85.0, 15.0)


def test_resolve_min_dynamic_threshold_default_full_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from feature_store.jacksparrow_v43_train_multihead import resolve_min_dynamic_threshold

    monkeypatch.delenv("V43_MIN_THRESHOLD_COST_FRACTION", raising=False)
    assert resolve_min_dynamic_threshold(0.001) == pytest.approx(0.001)


def test_resolve_min_dynamic_threshold_fraction_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from feature_store.jacksparrow_v43_train_multihead import resolve_min_dynamic_threshold

    monkeypatch.setenv("V43_MIN_THRESHOLD_COST_FRACTION", "1.5")
    assert resolve_min_dynamic_threshold(0.001) == pytest.approx(0.0015)


def test_compute_v43_round_trip_cost_matches_runtime_gate5() -> None:
    from agent.core.v43_signal_gates import round_trip_cost_pct
    from feature_store.jacksparrow_v43_train_multihead import compute_v43_round_trip_cost_pct

    train_cost = compute_v43_round_trip_cost_pct(maker_fee=0.0002, slippage=0.0003)
    assert train_cost == pytest.approx(0.001)
    # Runtime default fees match training defaults when settings use same fee/slip.
    assert train_cost == pytest.approx(round_trip_cost_pct(), rel=0.05)


def test_format_horizon_training_diagnostics_includes_heads() -> None:
    meta = {
        "target_definition": "cost_aware_forward_return",
        "runtime_cost_assumptions": {"round_trip_cost_pct": 0.0016},
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


def test_validate_multihead_export_gates_accepts_regressor_mean() -> None:
    meta = {
        "horizons": {
            key: {
                "validation_metrics": {
                    "inference_path": "regressor_mean",
                    "validation_corr": 0.10 if key == "scalp_10m" else 0.05,
                    "tradable_label_fraction": 0.25,
                }
            }
            for key in V43_MIN_META_AUC_BY_HORIZON
        }
    }
    failures = validate_multihead_export_gates(meta, strict=True)
    assert failures == []


def test_validate_multihead_export_gates_passes_strong_model() -> None:
    horizons = {}
    for key, min_auc in V43_MIN_META_AUC_BY_HORIZON.items():
        horizons[key] = {
            "validation_metrics": {
                "inference_path": "meta_calibrator",
                "meta_auc": min_auc + 0.02,
                "validation_corr": 0.10 if key == "scalp_10m" else 0.05,
                "tradable_label_fraction": 0.25,
            }
        }
    failures = validate_multihead_export_gates({"horizons": horizons}, strict=True)
    assert failures == []


def test_primary_execution_horizon_bars_requires_metadata_key() -> None:
    with pytest.raises(ValueError, match="missing primary_execution_horizon_bars"):
        primary_execution_horizon_bars({})


def test_primary_execution_horizon_bars_rejects_invalid_bars() -> None:
    with pytest.raises(ValueError, match="not in"):
        primary_execution_horizon_bars({"primary_execution_horizon_bars": 99})


def test_primary_execution_horizon_bars_returns_scalp() -> None:
    assert primary_execution_horizon_bars({"primary_execution_horizon_bars": 2}) == 2
