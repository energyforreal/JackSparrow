"""Trade confluence scoring — facade over entry_quality evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.entry_quality import EntryQualityResult, evaluate_entry_quality
from agent.core.multi_horizon_evidence import MultiHorizonMLEvidence
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)


@dataclass
class TradeScoreResult:
    score: float
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


def score_trade_setup(
    *,
    strategy: StrategyCandidate,
    ml_validation: MLValidationSnapshot,
    structure: MarketStructureSnapshot,
    ml_confirms: bool,
    multi_horizon_evidence: Optional[MultiHorizonMLEvidence] = None,
    market_context: Optional[dict] = None,
    collapse_rate: Optional[float] = None,
) -> TradeScoreResult:
    """Weighted quality score (0–100) via unified entry_quality evaluator."""
    result = evaluate_entry_quality(
        strategy=strategy,
        ml_validation=ml_validation,
        structure=structure,
        ml_confirms=ml_confirms,
        market_context=market_context,
        collapse_rate=collapse_rate,
    )
    components = {k: round(v * 100.0, 2) for k, v in result.dimensions.items()}
    return TradeScoreResult(
        score=result.quality_score,
        passed=result.passed,
        components=components,
        reason_codes=result.reason_codes,
    )


__all__ = ["TradeScoreResult", "score_trade_setup", "EntryQualityResult", "evaluate_entry_quality"]
