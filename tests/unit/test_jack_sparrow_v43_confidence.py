"""Tests for v43 primary-head confidence scaling."""

from __future__ import annotations

import pytest

from agent.models.jack_sparrow_v43_node import _v43_head_confidence


def test_confidence_scales_with_edge_over_threshold() -> None:
    thr = 0.0011
    low = _v43_head_confidence(0.0002, thr, unc_scale=1.0)
    mid = _v43_head_confidence(0.00055, thr, unc_scale=1.0)
    high = _v43_head_confidence(0.0011, thr, unc_scale=1.0)
    assert low < mid < high
    assert high == pytest.approx(1.0)


def test_confidence_can_exceed_min_threshold_for_realistic_edge() -> None:
    thr = 0.0011
    edge = 0.0009  # strong but realistic expected_return edge
    conf = _v43_head_confidence(edge, thr, unc_scale=1.0)
    assert conf >= 0.70


def test_confidence_respects_uncertainty_scale() -> None:
    thr = 0.0011
    edge = 0.0009
    full = _v43_head_confidence(edge, thr, unc_scale=1.0)
    damped = _v43_head_confidence(edge, thr, unc_scale=0.5)
    assert damped == pytest.approx(full * 0.5)


def test_confidence_clamped_to_unit_interval() -> None:
    thr = 0.0011
    conf = _v43_head_confidence(0.01, thr, unc_scale=1.5)
    assert 0.0 <= conf <= 1.0
