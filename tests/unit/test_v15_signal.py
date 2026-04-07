"""Unit tests for v15 entry edge buffer and gate."""

from agent.core.v15_signal import (
    evaluate_v15_entry,
    rolling_edge_threshold,
    apply_v15_entry_gate,
    _edge_buffers,
)


def setup_function() -> None:
    for k in _edge_buffers:
        _edge_buffers[k].clear()


def test_rolling_edge_threshold_uses_floor_when_sparse() -> None:
    assert rolling_edge_threshold("5m") >= 0.0


def test_evaluate_v15_entry_hold_on_low_vol_filter(monkeypatch) -> None:
    monkeypatch.setattr("agent.core.v15_signal.settings.volatility_filter_enabled", True)
    monkeypatch.setattr("agent.core.v15_signal.settings.v15_atr_pct_floor", 0.0005)
    for _ in range(25):
        _edge_buffers["5m"].append(0.5)
    sig, diag = evaluate_v15_entry(
        "5m",
        0.9,
        {"atr_pct": 0.0001, "adx_14": 10.0, "atr_14": 100.0, "close": 50000.0},
    )
    assert sig == "HOLD"
    assert diag.get("volatility_filter_passed") is False


def test_apply_v15_entry_gate_noop_without_v15_models(monkeypatch) -> None:
    monkeypatch.setattr("agent.core.v15_signal.settings.v15_signal_logic_enabled", True)
    sig, diag = apply_v15_entry_gate(
        "BUY",
        [{"model_name": "x", "prediction": 0.5, "context": {"format": "v4"}}],
        {"atr_pct": 0.002, "adx_14": 15.0},
    )
    assert sig == "BUY"
    assert diag == {}
