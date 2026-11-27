"""Unit tests for transformer plan fields forwarded onto WS signal payloads."""

from backend.services.agent_event_subscriber import (
    _market_context_excerpt,
    _transformer_plan_ws_fields,
    algorithmic_signal_fields,
)


def test_transformer_plan_ws_fields_copies_execution_plan_and_mtf() -> None:
    market_context = {
        "decision_path": "transformer_agent_synthesis",
        "long_edge": 0.012,
        "short_edge": -0.012,
        "winning_edge": 0.012,
        "primary_tf": "tf_15m",
        "transformer_vol_regime": "NORMAL",
        "path_edge": 0.012,
        "threshold": 0.005,
        "execution_plan": {
            "signal": "BUY",
            "size_scale": 0.7,
            "size_fraction": 0.42,
            "stop_loss_pct": 0.004,
            "take_profit_pct": 0.008,
            "rr_soft_action": "reduce_size",
            "long_edge": 0.012,
            "short_edge": -0.012,
        },
        "multi_tf_predictions": {
            "tf_15m": {"local_signal": "BUY", "path_edge": 0.01},
        },
        "cross_tf_summary": {"aligned": True},
    }

    out = _transformer_plan_ws_fields(market_context)

    assert out["decision_path"] == "transformer_agent_synthesis"
    assert out["long_edge"] == 0.012
    assert out["short_edge"] == -0.012
    assert out["winning_edge"] == 0.012
    assert out["primary_tf"] == "tf_15m"
    assert out["transformer_vol_regime"] == "NORMAL"
    assert out["execution_plan"]["size_scale"] == 0.7
    assert out["execution_plan"]["rr_soft_action"] == "reduce_size"
    assert out["multi_tf_predictions"]["tf_15m"]["local_signal"] == "BUY"
    assert out["cross_tf_summary"]["aligned"] is True


def test_transformer_plan_ws_fields_fills_edges_from_plan_when_mctx_omits() -> None:
    market_context = {
        "execution_plan": {
            "long_edge": 0.009,
            "short_edge": -0.009,
            "winning_edge": 0.009,
            "primary_tf": "tf_5m",
            "size_fraction": 0.3,
        }
    }
    out = _transformer_plan_ws_fields(market_context)
    assert out["long_edge"] == 0.009
    assert out["short_edge"] == -0.009
    assert out["winning_edge"] == 0.009
    assert out["primary_tf"] == "tf_5m"
    assert out["execution_plan"]["size_fraction"] == 0.3


def test_transformer_plan_ws_fields_empty_for_non_dict() -> None:
    assert _transformer_plan_ws_fields(None) == {}
    assert _transformer_plan_ws_fields("x") == {}


def test_market_context_excerpt_includes_execution_plan() -> None:
    market_context = {
        "trade_score": 80,
        "execution_plan": {"size_scale": 1.0},
        "long_edge": 0.01,
        "decision_path": "transformer_agent_synthesis",
        "unrelated": "drop_me",
    }
    excerpt = _market_context_excerpt(market_context)
    assert excerpt["trade_score"] == 80
    assert excerpt["execution_plan"]["size_scale"] == 1.0
    assert excerpt["long_edge"] == 0.01
    assert excerpt["decision_path"] == "transformer_agent_synthesis"
    assert "unrelated" not in excerpt


def test_algorithmic_decision_ready_keeps_size_and_authorization_separate() -> None:
    payload = {
        "symbol": "BTCUSD",
        "signal": "BUY",
        "confidence": 0.82,
        "trading_decision": {
            "decision_path": "algorithmic",
            "score": 82,
            "execution_authorized": False,
            "risk": {"stop_loss": 90.0, "take_profit": 120.0, "position_size": 0.0},
        },
    }
    out = algorithmic_signal_fields(payload, {"decision_path": "algorithmic"})
    decision = out["trading_decision"]
    assert decision["execution_authorized"] is False
    assert decision["risk"]["position_size"] == 0.0

    rebuilt = algorithmic_signal_fields(
        {"symbol": "BTCUSD", "signal": "HOLD", "confidence": 0.0},
        {
            "decision_path": "algorithmic",
            "algo_score": 0.0,
            "invalidation": "five_minute_not_closed",
            "decision_id": "decision-1",
            "candle_timestamp": "2026-11-13T10:45:00+00:00",
            "timeframes": {"5m": {"confirmation": 0.0}},
        },
    )
    held = rebuilt["trading_decision"]
    assert held["execution_authorized"] is False
    assert held["risk"]["position_size"] == 0.0
    assert held["invalidation"] == ["five_minute_not_closed"]
    assert held["decision_id"] == "decision-1"
    assert held["market_context"]["5m"]["confirmation"] == 0.0
