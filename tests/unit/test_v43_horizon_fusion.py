"""Policy and thesis multi-head fusion tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent.core.agent_policy_engine import _fuse_signals
from agent.core.agent_thesis_engine import ThesisVerdict
from agent.core.multi_horizon_evidence import build_multi_horizon_evidence
from agent.events.schemas import MLEvidenceSnapshot
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEYS


def _fixture_meta() -> dict:
    p = Path(__file__).resolve().parents[1] / "fixtures" / "v43_multihead_metadata.json"
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def _mh_context(*, long_heads: bool = True) -> dict:
    meta = _fixture_meta()
    payloads = {
        k: {
            "forward_bars": {"scalp_10m": 2, "intraday_30m": 6, "trend_1h": 12, "swing_2h": 24}[k],
            "expected_return": 0.02,
            "threshold": 0.005,
            "short_threshold": 0.005,
            "regime": "neutral",
        }
        for k in V43_HORIZON_KEYS
    }
    if not long_heads:
        payloads["intraday_30m"]["expected_return"] = -0.02
    return {
        "multi_horizon_evidence": build_multi_horizon_evidence(
            payloads, meta, short_enabled=True
        ).to_dict(),
        "v43_bundle_metadata": meta,
    }


def _ml_evidence(**kwargs) -> MLEvidenceSnapshot:
    base = dict(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="BUY",
        ml_candidate_confidence=0.7,
        ml_candidate_position_size=0.05,
    )
    base.update(kwargs)
    return MLEvidenceSnapshot(**base)


def test_ml_and_thesis_blocks_thesis_head_disagreement() -> None:
    thesis = ThesisVerdict(
        signal="BUY",
        confidence=0.8,
        position_size=0.05,
        thesis_type="trend_continuation",
        intended_horizon_bars=6,
        horizon_minutes=30,
    )
    ctx = _mh_context(long_heads=False)
    verdict = _fuse_signals(
        _ml_evidence(),
        thesis,
        "ml_and_thesis",
        "",
        market_context=ctx,
    )
    assert verdict.signal == "HOLD"
    assert any("thesis_head_disagrees" in r for r in verdict.reason_codes)


def test_ml_and_thesis_agrees_when_heads_align() -> None:
    thesis = ThesisVerdict(
        signal="BUY",
        confidence=0.8,
        position_size=0.05,
        thesis_type="trend_continuation",
        intended_horizon_bars=6,
        horizon_minutes=30,
    )
    ctx = _mh_context(long_heads=True)
    verdict = _fuse_signals(
        _ml_evidence(),
        thesis,
        "ml_and_thesis",
        "",
        market_context=ctx,
    )
    assert verdict.signal == "BUY"
    assert "agent_thesis_confirms_ml" in verdict.reason_codes
