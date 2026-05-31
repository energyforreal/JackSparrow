"""Export gate blocking behavior for MSO training notebook."""

from __future__ import annotations

import os


def _run_export_gates(
    f1_scores: dict,
    *,
    primary_horizons: tuple[str, ...],
    dimensions: tuple[str, ...],
    min_f1_macro: float = 0.40,
    min_f1_macro_trend: float = 0.50,
    min_balanced_acc: float = 0.35,
) -> list[str]:
    failures: list[str] = []
    for hk in primary_horizons:
        for dim in dimensions:
            metrics = f1_scores.get(hk, {}).get(dim)
            if not isinstance(metrics, dict):
                failures.append(f"{hk}/{dim}: no metrics (head skipped or insufficient val)")
                continue
            f1m = float(metrics.get("f1_macro", 0.0))
            bal = float(metrics.get("balanced_accuracy", 0.0))
            min_f1 = min_f1_macro_trend if dim == "trend_regime" else min_f1_macro
            if f1m < min_f1:
                failures.append(f"{hk}/{dim}: f1_macro {f1m:.3f} < {min_f1:.3f}")
            if bal < min_balanced_acc:
                failures.append(
                    f"{hk}/{dim}: balanced_accuracy {bal:.3f} < {min_balanced_acc:.3f}"
                )
    return failures


def _export_blocked(failures: list[str]) -> bool:
    block = os.environ.get("MSO_BLOCK_EXPORT_ON_FAIL", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return block and bool(failures)


def test_export_blocked_by_default_when_gates_fail():
    f1_scores = {
        "scalp_10m": {
            "vol_regime": {"f1_macro": 0.21, "balanced_accuracy": 0.21},
        }
    }
    failures = _run_export_gates(
        f1_scores,
        primary_horizons=("scalp_10m",),
        dimensions=("vol_regime",),
    )
    assert failures
    assert _export_blocked(failures) is True


def test_export_allowed_when_override_and_gates_fail(monkeypatch):
    monkeypatch.setenv("MSO_BLOCK_EXPORT_ON_FAIL", "false")
    failures = ["scalp_10m/vol_regime: f1_macro 0.210 < 0.400"]
    assert _export_blocked(failures) is False


def test_export_allowed_when_gates_pass():
    f1_scores = {
        "scalp_10m": {
            "vol_regime": {"f1_macro": 0.55, "balanced_accuracy": 0.48},
        }
    }
    failures = _run_export_gates(
        f1_scores,
        primary_horizons=("scalp_10m",),
        dimensions=("vol_regime",),
    )
    assert failures == []
    assert _export_blocked(failures) is False
