"""Multi-head ML evidence and policy validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.core.agent_policy_engine import _fuse_signals
from agent.core.agent_thesis_engine import ThesisVerdict
from agent.core.multi_horizon_evidence import (
    build_multi_horizon_evidence,
    validate_thesis_against_multi_horizon,
)
from agent.events.schemas import MLEvidenceSnapshot
from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    validate_v43_metadata_compatibility,
)
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEYS


def _fixture_meta() -> dict:
    p = Path(__file__).resolve().parents[1] / "fixtures" / "v43_multihead_metadata.json"
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _head_payloads_long() -> dict:
    return {
        k: {
            "forward_bars": {"scalp_10m": 2, "intraday_30m": 6, "trend_1h": 12, "swing_2h": 24}[k],
            "expected_return": 0.02,
            "threshold": 0.005,
            "short_threshold": 0.005,
            "regime": "neutral",
        }
        for k in V43_HORIZON_KEYS
    }


def test_validate_multihead_metadata_fixture() -> None:
    meta = _fixture_meta()
    assert tuple(meta["features"]) == V43_CANONICAL_FEATURES
    validate_v43_metadata_compatibility(meta)


def test_thesis_validation_passes_aligned_heads() -> None:
    meta = _fixture_meta()
    evidence = build_multi_horizon_evidence(_head_payloads_long(), meta)
    ok, reasons = validate_thesis_against_multi_horizon("LONG", 6, evidence)
    assert ok
    assert any("multi_horizon_validation_passed" in r for r in reasons)


def test_thesis_validation_rejects_opposition() -> None:
    meta = _fixture_meta()
    payloads = _head_payloads_long()
    payloads["swing_2h"]["expected_return"] = -0.02
    evidence = build_multi_horizon_evidence(payloads, meta, short_enabled=True)
    ok, reasons = validate_thesis_against_multi_horizon("LONG", 6, evidence)
    assert not ok
    assert any("opposition" in r for r in reasons)


def test_policy_ml_and_thesis_uses_multi_horizon() -> None:
    meta = _fixture_meta()
    mh = build_multi_horizon_evidence(_head_payloads_long(), meta).to_dict()
    thesis = ThesisVerdict(
        signal="BUY",
        confidence=0.8,
        position_size=0.05,
        thesis_type="trend_continuation",
        intended_horizon_bars=6,
        horizon_minutes=30,
    )
    ml_ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.7,
        ml_candidate_position_size=0.05,
    )
    verdict = _fuse_signals(
        ml_ev,
        thesis,
        "ml_and_thesis",
        "",
        market_context={
            "multi_horizon_evidence": mh,
            "v43_bundle_metadata": meta,
            "v43_training_forward_bars": 6,
        },
    )
    assert verdict.signal == "BUY"
    assert any("multi_horizon_validation_passed" in r for r in verdict.reason_codes)


def test_policy_rejects_thesis_head_disagreement() -> None:
    meta = _fixture_meta()
    payloads = _head_payloads_long()
    payloads["intraday_30m"]["expected_return"] = -0.02
    mh = build_multi_horizon_evidence(payloads, meta).to_dict()
    thesis = ThesisVerdict(
        signal="BUY",
        confidence=0.8,
        position_size=0.05,
        thesis_type="trend_continuation",
        intended_horizon_bars=6,
        horizon_minutes=30,
    )
    ml_ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.7,
        ml_candidate_position_size=0.05,
    )
    verdict = _fuse_signals(
        ml_ev,
        thesis,
        "ml_and_thesis",
        "",
        market_context={"multi_horizon_evidence": mh, "v43_bundle_metadata": meta},
    )
    assert verdict.signal == "HOLD"
    assert any("thesis_head_disagrees" in r for r in verdict.reason_codes)
