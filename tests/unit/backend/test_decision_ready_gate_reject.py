"""Tests for v43 gate reject propagation on decision_ready signal payloads."""

from backend.services.agent_event_subscriber import _v43_gate_reject_from_context


def test_v43_gate_reject_from_market_context_dict():
    market_context = {"v43_gate_reject": "expected_return_below_threshold"}
    assert _v43_gate_reject_from_context({}, market_context) == "expected_return_below_threshold"


def test_v43_gate_reject_from_reasoning_chain_market_context():
    reasoning_chain = {
        "market_context": {"v43_gate_reject": "regime_unfavorable"},
    }
    assert _v43_gate_reject_from_context(reasoning_chain, {}) == "regime_unfavorable"


def test_v43_gate_reject_prefers_direct_market_context():
    reasoning_chain = {
        "market_context": {"v43_gate_reject": "from_chain"},
    }
    market_context = {"v43_gate_reject": "from_direct"}
    assert _v43_gate_reject_from_context(reasoning_chain, market_context) == "from_direct"


def test_decision_ready_signal_data_includes_gate_reject():
    """Mirror decision_ready consolidated handler gate-reject wiring."""
    reasoning_chain = {
        "steps": [],
        "conclusion": "",
        "market_context": {"v43_gate_reject": "below_threshold"},
    }
    market_context = reasoning_chain.get("market_context", {})

    signal_data = {}
    rj = _v43_gate_reject_from_context(reasoning_chain, market_context)
    if rj:
        signal_data["v43_gate_reject"] = rj

    assert signal_data["v43_gate_reject"] == "below_threshold"
