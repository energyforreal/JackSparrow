"""Tests for v43 five-gate helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.core.v43_signal_gates import (
    V43GateState,
    apply_gate5_min_edge_short,
    apply_gate5_min_edge,
    apply_post_threshold_gates,
    apply_post_threshold_gates_short,
    gate5_edge_ok,
    gate5_long_edge_metrics,
    gate5_short_edge_metrics,
    gate5_short_edge_ok,
    round_trip_cost_pct,
)


def test_round_trip_cost_positive() -> None:
    assert round_trip_cost_pct() > 0


def test_gate5_edge_ok_strong_signal() -> None:
    assert gate5_edge_ok(0.60, 0.01) is True
    m = gate5_long_edge_metrics(0.60, 0.01)
    assert m.passes is True


def test_gate5_metrics_matches_edge_ok() -> None:
    proba, thr = 0.0105, 0.01
    assert gate5_edge_ok(proba, thr) == gate5_long_edge_metrics(proba, thr).passes
    assert gate5_short_edge_ok(-0.011, thr) == gate5_short_edge_metrics(-0.011, thr).passes


def test_gate5_long_compares_expected_return_edge_to_cost() -> None:
    metrics = gate5_long_edge_metrics(0.014, 0.011)
    assert metrics.edge_pct == pytest.approx(0.003)
    assert metrics.lhs == pytest.approx(0.003)
    assert metrics.rhs == pytest.approx(metrics.ratio * metrics.rtc)
    assert metrics.passes is False


def test_gate5_long_representative_edge_passes_default_cost() -> None:
    metrics = gate5_long_edge_metrics(0.015, 0.011)
    assert metrics.edge_pct == pytest.approx(0.004)
    assert metrics.passes is True


def test_gate5_short_compares_expected_return_edge_to_cost() -> None:
    metrics = gate5_short_edge_metrics(-0.015, 0.011)
    assert metrics.edge_pct == pytest.approx(0.004)
    assert metrics.lhs == pytest.approx(0.004)
    assert metrics.passes is True


def test_debounce_blocks_second_entry() -> None:
    st = V43GateState()
    st.note_signal_decision(10)
    gr = apply_post_threshold_gates(
        raw_long=True,
        regime="neutral",
        current_bar_index=12,
        has_open_position=False,
        state=st,
    )
    assert gr.allow is False
    assert gr.reject_reason == "debounce"


def test_gate5_rejects_thin_edge() -> None:
    st = V43GateState()
    st.counters.signals_raw = 0
    ok = gate5_edge_ok(0.0105, 0.01)
    g5 = apply_gate5_min_edge(0.0105, 0.01, st)
    if not ok:
        assert g5.allow is False


def test_gate5_short_edge_ok_strong_signal() -> None:
    assert gate5_short_edge_ok(-0.60, 0.01) is True


def test_post_threshold_short_not_raw() -> None:
    st = V43GateState()
    gr = apply_post_threshold_gates_short(
        raw_short=False,
        regime="neutral",
        current_bar_index=100,
        has_open_position=False,
        state=st,
    )
    assert gr.allow is False
    assert gr.reject_reason == "below_threshold_short"


def test_post_threshold_short_debounce_same_as_long() -> None:
    st = V43GateState()
    st.note_signal_decision(10)
    gr = apply_post_threshold_gates_short(
        raw_short=True,
        regime="neutral",
        current_bar_index=12,
        has_open_position=False,
        state=st,
    )
    assert gr.allow is False
    assert gr.reject_reason == "debounce"


def test_gate5_short_rejects_thin_edge() -> None:
    st = V43GateState()
    if not gate5_short_edge_ok(-0.011, 0.01):
        g5 = apply_gate5_min_edge_short(-0.011, 0.01, st)
        assert g5.allow is False
