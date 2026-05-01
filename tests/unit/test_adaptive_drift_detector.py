"""Tests for KS drift detection."""

import numpy as np
import pandas as pd

from agent.learning.adaptive.drift_detector import (
    detect_drift,
    should_retrain_from_drift,
)


def test_detect_drift_no_shift() -> None:
    rng = np.random.default_rng(42)
    base = rng.normal(0, 1, 5000)
    df_past = pd.DataFrame({"f1": base})
    df_recent = pd.DataFrame({"f1": rng.normal(0, 1, 5000)})
    out = detect_drift(df_past, df_recent, ["f1"], alpha=0.01, stat_threshold=0.10)
    assert len(out) == 0


def test_detect_drift_large_shift() -> None:
    rng = np.random.default_rng(0)
    df_past = pd.DataFrame({"f1": rng.normal(0, 1, 8000)})
    df_recent = pd.DataFrame({"f1": rng.normal(5.0, 1, 8000)})
    out = detect_drift(df_past, df_recent, ["f1"], alpha=0.01, stat_threshold=0.10)
    assert len(out) >= 1
    assert out[0][0] == "f1"


def test_should_retrain_from_drift() -> None:
    drifted = [("a", 0.001, 0.2), ("b", 0.001, 0.15)]
    assert should_retrain_from_drift(drifted, feature_limit=1) is True
    assert should_retrain_from_drift([("a", 0.01, 0.05)], feature_limit=5) is False
