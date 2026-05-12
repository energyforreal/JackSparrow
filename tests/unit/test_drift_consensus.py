"""KS+PSI consensus drift feature list."""

from __future__ import annotations

from agent.learning.adaptive.drift_detector import consensus_drift_feature_names


def test_consensus_intersection() -> None:
    ks = [("a", 0.0, 0.2), ("b", 0.0, 0.2)]
    psi = [("b", 0.3), ("c", 0.4)]
    names = consensus_drift_feature_names(ks, psi)
    assert names == ["b"]
