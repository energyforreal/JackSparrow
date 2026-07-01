"""Pre-trade market validation — separates market understanding from execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.intelligence.regime_benchmark import attach_regime_benchmark, derive_regime_benchmark


@dataclass
class MarketValidationResult:
    """Structured market validation for one evaluation cycle."""

    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    validation_score: float = 0.0
    regime_benchmark: str = "ranging"
    trending: bool = False
    breakout_genuine: bool = False
    volatility_suitable: bool = False
    mtf_aligned: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks_passed": list(self.checks_passed),
            "checks_failed": list(self.checks_failed),
            "validation_score": round(self.validation_score, 2),
            "regime_benchmark": self.regime_benchmark,
            "trending": self.trending,
            "breakout_genuine": self.breakout_genuine,
            "volatility_suitable": self.volatility_suitable,
            "mtf_aligned": self.mtf_aligned,
        }


def validate_market(
    *,
    market_state: Dict[str, Any],
    gate_categories: Optional[Dict[str, bool]] = None,
) -> MarketValidationResult:
    """Evaluate whether market conditions support signal quality assessment."""
    ms = attach_regime_benchmark(dict(market_state))
    gates = gate_categories or {}
    passed: List[str] = []
    failed: List[str] = []
    score = 50.0

    trend = str(ms.get("trend") or "neutral").lower()
    strength = str(ms.get("trend_strength") or "weak").lower()
    trending = trend in ("bullish", "bearish") and strength != "weak"
    if trending:
        passed.append("market_trending")
        score += 15.0
    else:
        failed.append("market_not_trending")

    breakout = str(ms.get("breakout_status") or "none").lower()
    breakout_genuine = breakout in ("confirmed", "forming")
    if breakout_genuine:
        passed.append("breakout_genuine")
        score += 10.0
    elif breakout == "failed":
        failed.append("breakout_failed")

    vol_cat = bool(gates.get("volatility", True))
    volatility_suitable = vol_cat and str(ms.get("volatility") or "") != "compressing"
    if volatility_suitable:
        passed.append("volatility_suitable")
        score += 10.0
    else:
        failed.append("volatility_unsuitable")

    mtf = ms.get("mtf") if isinstance(ms.get("mtf"), dict) else {}
    h1 = str(mtf.get("h1") or "").lower()
    mtf_aligned = "counter" not in h1
    if mtf_aligned:
        passed.append("mtf_aligned")
        score += 10.0
    else:
        failed.append("mtf_counter")

    if bool(gates.get("liquidity", True)):
        passed.append("liquidity_ok")
        score += 5.0
    else:
        failed.append("liquidity_stressed")

    benchmark = derive_regime_benchmark(ms)
    return MarketValidationResult(
        checks_passed=passed,
        checks_failed=failed,
        validation_score=max(0.0, min(100.0, score)),
        regime_benchmark=benchmark,
        trending=trending,
        breakout_genuine=breakout_genuine,
        volatility_suitable=volatility_suitable,
        mtf_aligned=mtf_aligned,
    )
