"""
Rule-based agent thesis engine — independent trade intent from market structure.

Evaluates closed-bar features and regime without ML. Used by AgentPolicyEngine
for signal fusion (ml_only, thesis_only, ml_or_thesis, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import structlog

from agent.core.config import settings

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_DEFAULT_POSITION_SIZE = 0.05

# Regime -> which thesis rule families may run
_REGIME_ALLOWED_RULES: Dict[str, Set[str]] = {
    "crisis": set(),
    "trending": {"trend_continuation"},
    "neutral": {"breakout", "trend_continuation"},
    "ranging": {"mean_reversion"},
    "unknown": {"breakout", "trend_continuation"},
}

_last_thesis_snapshot: Dict[str, Any] = {}


@dataclass
class ThesisVerdict:
    """Rule-based agent thesis for one decision cycle."""

    signal: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    confidence: float
    position_size: float
    reason_codes: List[str] = field(default_factory=list)
    thesis_type: str = "flat"  # breakout | trend_continuation | mean_reversion | flat | crisis_veto


def get_last_thesis_snapshot() -> Dict[str, Any]:
    """Last thesis evaluation (for health / dashboard)."""
    return dict(_last_thesis_snapshot)


def _feat(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _normalize_regime(regime: Optional[str]) -> str:
    r = str(regime or "neutral").strip().lower()
    if r in _REGIME_ALLOWED_RULES:
        return r
    return "neutral"


def _allowed_rules_for_regime(regime: str) -> Set[str]:
    return set(_REGIME_ALLOWED_RULES.get(regime, _REGIME_ALLOWED_RULES["neutral"]))


class AgentThesisEngine:
    """Pure rule-based market thesis from features + regime."""

    def evaluate(
        self,
        regime: Optional[str],
        market_context: Optional[Dict[str, Any]],
    ) -> ThesisVerdict:
        """Return thesis signal from structural rules (no ML)."""
        global _last_thesis_snapshot
        mc = market_context if isinstance(market_context, dict) else {}
        features = mc.get("features") if isinstance(mc.get("features"), dict) else {}
        reg = _normalize_regime(regime or mc.get("v43_regime") or mc.get("regime"))
        allowed = _allowed_rules_for_regime(reg)

        if bool(mc.get("has_open_position", False)):
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_open_position"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        squeeze = max(
            _feat(features, "long_squeeze_risk"),
            _feat(features, "short_squeeze_risk"),
            float(mc.get("squeeze_risk") or 0.0),
        )
        if squeeze > float(getattr(settings, "agent_thesis_squeeze_veto_threshold", 0.5) or 0.5):
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_squeeze_veto", f"squeeze_risk={squeeze:.3f}"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        if reg == "crisis" and bool(getattr(settings, "agent_thesis_crisis_veto", True)):
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_crisis_regime_veto"],
                thesis_type="crisis_veto",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        pos_size = float(
            getattr(settings, "jacksparrow_v43_max_position_pct", _DEFAULT_POSITION_SIZE)
            or _DEFAULT_POSITION_SIZE
        )
        pos_size = max(0.01, min(0.2, pos_size))

        if "breakout" in allowed and bool(getattr(settings, "agent_thesis_breakout_enabled", True)):
            br = self._eval_breakout_long(features, reg)
            if br is not None:
                br.position_size = pos_size
                _store_snapshot(reg, allowed, br)
                return br

        if "trend_continuation" in allowed and bool(
            getattr(settings, "agent_thesis_trend_enabled", True)
        ):
            tr = self._eval_trend_continuation_long(features, reg)
            if tr is not None:
                tr.position_size = pos_size
                _store_snapshot(reg, allowed, tr)
                return tr

        if "mean_reversion" in allowed and bool(
            getattr(settings, "agent_thesis_mean_reversion_enabled", False)
        ):
            mr = self._eval_mean_reversion_long(features)
            if mr is not None:
                mr.position_size = pos_size
                _store_snapshot(reg, allowed, mr)
                return mr

        verdict = ThesisVerdict(
            signal="HOLD",
            confidence=0.0,
            position_size=0.0,
            reason_codes=["thesis_no_rule_fired", f"regime={reg}"],
            thesis_type="flat",
        )
        _store_snapshot(reg, allowed, verdict)
        return verdict

    def _eval_breakout_long(
        self, features: Dict[str, Any], regime: str
    ) -> Optional[ThesisVerdict]:
        adx = _feat(features, "adx_14")
        di = _feat(features, "di_spread")
        vol_reg = _feat(features, "vol_regime", 1.0)
        h_trend = _feat(features, "h_trend")
        adx_min = float(getattr(settings, "agent_thesis_breakout_adx_min", 25.0) or 25.0)
        di_min = float(getattr(settings, "agent_thesis_breakout_di_min", 5.0) or 5.0)
        vol_min = float(getattr(settings, "agent_thesis_breakout_vol_regime_min", 1.1) or 1.1)

        if adx <= adx_min or di <= di_min or vol_reg <= vol_min or h_trend <= 0:
            return None

        conf = min(0.92, 0.65 + 0.01 * min(adx - adx_min, 15))
        return ThesisVerdict(
            signal="BUY",
            confidence=conf,
            position_size=0.0,
            reason_codes=[
                "thesis_breakout_long",
                f"adx_14={adx:.2f}",
                f"di_spread={di:.2f}",
                f"vol_regime={vol_reg:.2f}",
                f"regime={regime}",
            ],
            thesis_type="breakout",
        )

    def _eval_trend_continuation_long(
        self, features: Dict[str, Any], regime: str
    ) -> Optional[ThesisVerdict]:
        h1 = _feat(features, "h1_trend")
        h = _feat(features, "h_trend")
        rsi = _feat(features, "rsi_14", 50.0)
        hurst = _feat(features, "hurst_60", 0.5)
        rsi_lo = float(getattr(settings, "agent_thesis_trend_rsi_lo", 40.0) or 40.0)
        rsi_hi = float(getattr(settings, "agent_thesis_trend_rsi_hi", 65.0) or 65.0)
        hurst_min = float(getattr(settings, "agent_thesis_trend_hurst_min", 0.52) or 0.52)

        if h1 <= 0 or h <= 0 or rsi < rsi_lo or rsi > rsi_hi or hurst < hurst_min:
            return None

        conf = min(0.88, 0.6 + 0.15 * min(h1 * 100, 1.0))
        return ThesisVerdict(
            signal="BUY",
            confidence=conf,
            position_size=0.0,
            reason_codes=[
                "thesis_trend_continuation_long",
                f"h1_trend={h1:.4f}",
                f"h_trend={h:.4f}",
                f"rsi_14={rsi:.2f}",
                f"hurst_60={hurst:.3f}",
                f"regime={regime}",
            ],
            thesis_type="trend_continuation",
        )

    def _eval_mean_reversion_long(self, features: Dict[str, Any]) -> Optional[ThesisVerdict]:
        rsi = _feat(features, "rsi_14", 50.0)
        bb = _feat(features, "bb_pos", 0.5)
        rsi_max = float(getattr(settings, "agent_thesis_mr_rsi_max", 32.0) or 32.0)
        bb_max = float(getattr(settings, "agent_thesis_mr_bb_pos_max", 0.15) or 0.15)

        if rsi > rsi_max or bb > bb_max:
            return None

        return ThesisVerdict(
            signal="BUY",
            confidence=0.62,
            position_size=0.0,
            reason_codes=[
                "thesis_mean_reversion_long",
                f"rsi_14={rsi:.2f}",
                f"bb_pos={bb:.3f}",
            ],
            thesis_type="mean_reversion",
        )


def _store_snapshot(regime: str, allowed: Set[str], verdict: ThesisVerdict) -> None:
    global _last_thesis_snapshot
    _last_thesis_snapshot = {
        "regime": regime,
        "allowed_rules": sorted(allowed),
        "signal": verdict.signal,
        "confidence": verdict.confidence,
        "thesis_type": verdict.thesis_type,
        "thesis_fires_this_bar": verdict.signal in _ENTRY_SIGNALS,
        "reason_codes": list(verdict.reason_codes),
    }


agent_thesis_engine = AgentThesisEngine()
