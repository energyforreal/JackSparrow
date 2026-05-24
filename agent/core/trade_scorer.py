"""Trade confluence scoring — aggregates thesis, ML validation, and structure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.config import settings
from agent.core.multi_horizon_evidence import MultiHorizonMLEvidence
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)


@dataclass
class TradeScoreResult:
    score: float  # 0-100
    passed: bool
    components: Dict[str, float]
    reason_codes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "components": self.components,
            "reason_codes": self.reason_codes,
        }


def _effective_direction(
    strategy: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
) -> str:
    """Use gated ML side when thesis is FLAT but v43 gates passed (perp long/short symmetry)."""
    if strategy.direction != "FLAT":
        return strategy.direction
    if ml_validation.final_short and not ml_validation.final_long:
        return "SHORT"
    if ml_validation.final_long and not ml_validation.final_short:
        return "LONG"
    return "FLAT"


def _multi_horizon_alignment_bonus(
    ml_validation: MLValidationSnapshot,
    strategy: StrategyCandidate,
) -> float:
    raw = ml_validation.multi_horizon_evidence
    if not isinstance(raw, dict):
        return 0.0
    try:
        align = float(raw.get("alignment_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        align = 0.0
    if strategy.direction == "FLAT" or align <= 0:
        return 0.0
    return min(10.0, align * 10.0)


def score_trade_setup(
    *,
    strategy: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
    structure: MarketStructureSnapshot,
    ml_confirms: bool,
    multi_horizon_evidence: Optional[MultiHorizonMLEvidence] = None,
) -> TradeScoreResult:
    """Weighted confluence score for strategy-first pipeline."""
    components: Dict[str, float] = {}
    reasons: List[str] = []
    direction = _effective_direction(strategy, ml_validation)
    if direction != strategy.direction and direction != "FLAT":
        reasons.append("score_effective_direction_from_ml_gates")

    thesis_pts = 0.0
    if direction in ("LONG", "SHORT"):
        strength = strategy.strength if strategy.direction != "FLAT" else 0.5
        thesis_pts = min(30.0, 15.0 + strength * 20.0)
        reasons.append("score_thesis_active")
    components["thesis"] = thesis_pts

    ml_pts = 0.0
    gated_ml = False
    if direction == "LONG":
        gated_ml = bool(ml_validation.final_long)
    elif direction == "SHORT":
        gated_ml = bool(ml_validation.final_short)
    if gated_ml and direction != "FLAT":
        thr_use = (
            ml_validation.threshold
            if direction == "LONG"
            else ml_validation.short_threshold
        )
        edge = abs(ml_validation.expected_return) - thr_use
        ml_pts = min(25.0, max(0.0, 10.0 + edge * 500.0))
        reasons.append("score_ml_gated_confirms")
    elif ml_confirms and direction != "FLAT":
        reasons.append("score_ml_ungated_skipped")
    components["ml"] = ml_pts

    regime_pts = 0.0
    if structure.market_type == "TRENDING" and strategy.thesis_type in (
        "breakout",
        "trend_continuation",
    ):
        regime_pts = 15.0
    elif structure.market_type == "RANGING" and strategy.thesis_type == "mean_reversion":
        regime_pts = 15.0
    elif structure.market_type not in ("CRISIS", "LOW_VOL"):
        regime_pts = 8.0
    components["regime_fit"] = regime_pts

    liquidity_pts = 15.0 if structure.liquidity_ok else 0.0
    if not structure.liquidity_ok:
        reasons.append("score_liquidity_penalty")
    components["liquidity"] = liquidity_pts

    structure_pts = 0.0 if structure.chop_market else 10.0
    if structure.chop_market:
        reasons.append("score_chop_penalty")
    components["structure"] = structure_pts

    gate_pts = 0.0
    if ml_validation.final_long or ml_validation.final_short:
        gate_pts = 10.0
        reasons.append("score_ml_gates_passed")
    components["gates"] = gate_pts

    mh_pts = _multi_horizon_alignment_bonus(
        ml_validation,
        StrategyCandidate(
            direction=direction,
            strength=strategy.strength,
            signal=strategy.signal,
            thesis_type=strategy.thesis_type,
            confidence=strategy.confidence,
        ),
    )
    if mh_pts > 0:
        reasons.append("score_multi_horizon_alignment")
    components["multi_horizon"] = mh_pts

    total = sum(components.values())
    min_score = float(getattr(settings, "agent_trade_score_min", 70.0) or 70.0)
    passed = total >= min_score and direction != "FLAT"
    if not passed and direction != "FLAT":
        reasons.append(f"score_below_min={total:.1f}<{min_score:.1f}")

    return TradeScoreResult(
        score=round(total, 2),
        passed=passed,
        components=components,
        reason_codes=reasons,
    )
