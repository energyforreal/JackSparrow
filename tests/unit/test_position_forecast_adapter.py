"""Unit tests for position forecast adapter."""

from agent.core.position_forecast_adapter import evaluate_forecast_adjustment


def test_forecast_exit_when_opposes_long() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {"expectation": {"dominant_expectation": "bullish", "confidence": 0.7}}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "bearish", "confidence": 0.72}
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    assert adj.hint == "exit_candidate"
    assert "forecast_opposes_position" in adj.reason_codes


def test_forecast_extend_when_aligned_upgrade() -> None:
    position = {"side": "long", "symbol": "BTCUSD"}
    entry = {"decision_context": {"expectation": {"dominant_expectation": "bullish", "confidence": 0.55}}}
    live = {
        "decision_context_v3": {
            "expectation": {"dominant_expectation": "bullish", "confidence": 0.68}
        }
    }
    adj = evaluate_forecast_adjustment(position, entry, live)
    assert adj.hint == "extend_tp"
