"""Integration replay tests using frozen telemetry fixtures."""

import json
from pathlib import Path

import pytest

from agent.core import agent_policy_engine as ape_mod
from agent.core.agent_policy_engine import AgentPolicyEngine
from agent.core.entry_quality import evaluate_entry_quality
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)
from agent.events.schemas import MLEvidenceSnapshot
from unittest.mock import MagicMock

from agent.core.agent_thesis_engine import ThesisVerdict

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "july2_telemetry"


@pytest.mark.parametrize("fixture_name", ["ml_only_short_flat_hypothesis.json"])
def test_july2_fixture_blocks_bad_entry(fixture_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    mc = raw["market_context"]
    strat = StrategyCandidate(
        direction=raw["strategy"]["direction"],
        strength=raw["strategy"]["strength"],
        signal=raw["strategy"]["signal"],
        thesis_type=raw["strategy"]["thesis_type"],
        confidence=raw["strategy"]["confidence"],
    )
    ml_raw = mc["ml_validation"]
    ml_val = MLValidationSnapshot(
        expected_return=float(ml_raw["expected_return"]),
        threshold=float(ml_raw["threshold"]),
        short_threshold=float(ml_raw["short_threshold"]),
        regime=str(mc.get("regime") or "neutral"),
        final_long=bool(ml_raw["final_long"]),
        final_short=bool(ml_raw["final_short"]),
    )
    eq = evaluate_entry_quality(
        strategy=strat,
        ml_validation=ml_val,
        structure=MarketStructureSnapshot(
            market_type="NEUTRAL", regime="neutral", liquidity_ok=True
        ),
        ml_confirms=bool(ml_raw["final_short"]),
        market_context=mc,
        collapse_rate=float(raw.get("collapse_rate", 0.0)),
    )
    assert eq.passed is False

    monkeypatch.setattr(ape_mod.settings, "agent_policy_mode", "ml_or_thesis")
    monkeypatch.setattr(ape_mod.settings, "agent_policy_force_hold", False)
    eng = MagicMock()
    eng.evaluate.return_value = ThesisVerdict(
        signal="HOLD",
        confidence=0.0,
        position_size=0.0,
        reason_codes=list(mc["hypothesis_snapshot"]["reason_codes"]),
        thesis_type="flat",
    )
    engine = AgentPolicyEngine(thesis_engine=eng)
    ev = MLEvidenceSnapshot(
        symbol="BTCUSD",
        source="v43_orchestrator",
        ml_candidate_signal="SHORT",
        ml_candidate_confidence=0.72,
        ml_candidate_position_size=0.05,
        ml_confirms=True,
    )
    verdict = engine.evaluate(ml_evidence=ev, market_context=mc)
    assert verdict.signal == raw["expected_policy_signal"]
