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
from feature_store.jacksparrow_v43_horizon import (
    forward_bars_to_minutes,
    thesis_intended_forward_bars,
)

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})
_DEFAULT_POSITION_SIZE = 0.05

# Regime -> which thesis rule families may run
_REGIME_ALLOWED_RULES: Dict[str, Set[str]] = {
    "crisis": set(),
    "trending": {"trend_continuation", "basis_crowding", "funding_crowding"},
    "neutral": {"breakout", "trend_continuation", "basis_crowding", "funding_crowding"},
    "ranging": {"mean_reversion"},
    "unknown": {"breakout", "trend_continuation", "basis_crowding", "funding_crowding"},
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
    intended_horizon_bars: int = 0
    horizon_minutes: int = 0


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

        if bool(mc.get("market_health_hold")):
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=[
                    "thesis_market_health_veto",
                    str(mc.get("market_health_reason") or "non_operational"),
                ],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

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

        structure = mc.get("market_structure") if isinstance(mc.get("market_structure"), dict) else {}
        if structure.get("chop_market") and bool(
            getattr(settings, "agent_thesis_chop_veto_enabled", True)
        ):
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_chop_market_veto"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        if structure.get("liquidity_ok") is False:
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_liquidity_veto"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        atr_pct = _feat(features, "atr_pct")
        atr_min = float(getattr(settings, "agent_thesis_min_atr_pct", 0.0) or 0.0)
        if atr_min > 0 and atr_pct > 0 and atr_pct < atr_min:
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_atr_too_low", f"atr_pct={atr_pct:.5f}"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        funding = _feat(features, "funding_pressure", 0.0)
        fund_max = float(getattr(settings, "agent_thesis_funding_pressure_max", 2.0) or 2.0)
        if abs(funding) > fund_max:
            verdict = ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_funding_spike_veto", f"funding_pressure={funding:.3f}"],
                thesis_type="flat",
            )
            _store_snapshot(reg, allowed, verdict)
            return verdict

        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )

        pos_size = float(
            getattr(settings, "jacksparrow_v43_max_position_pct", _DEFAULT_POSITION_SIZE)
            or _DEFAULT_POSITION_SIZE
        )
        pos_size = max(0.01, min(0.2, pos_size))

        verdict = self._select_best_thesis(
            self._collect_thesis_candidates(features, reg, allowed, short_enabled),
            pos_size=pos_size,
            regime=reg,
        )
        verdict = self._apply_price_band_veto(verdict, mc)
        _store_snapshot(reg, allowed, verdict)
        return verdict

    def _collect_thesis_candidates(
        self,
        features: Dict[str, Any],
        regime: str,
        allowed: Set[str],
        short_enabled: bool,
    ) -> List[ThesisVerdict]:
        """Evaluate all enabled long/short thesis rules (no long-first early return)."""
        candidates: List[ThesisVerdict] = []

        if "breakout" in allowed and bool(getattr(settings, "agent_thesis_breakout_enabled", True)):
            br = self._eval_breakout_long(features, regime)
            if br is not None:
                candidates.append(br)
            if short_enabled:
                brs = self._eval_breakout_short(features, regime)
                if brs is not None:
                    candidates.append(brs)

        if "trend_continuation" in allowed and bool(
            getattr(settings, "agent_thesis_trend_enabled", True)
        ):
            tr = self._eval_trend_continuation_long(features, regime)
            if tr is not None:
                candidates.append(tr)
            if short_enabled:
                trs = self._eval_trend_continuation_short(features, regime)
                if trs is not None:
                    candidates.append(trs)

        if "mean_reversion" in allowed and bool(
            getattr(settings, "agent_thesis_mean_reversion_enabled", False)
        ):
            mr = self._eval_mean_reversion_long(features)
            if mr is not None:
                candidates.append(mr)
            if short_enabled:
                mrs = self._eval_mean_reversion_short(features)
                if mrs is not None:
                    candidates.append(mrs)

        if "basis_crowding" in allowed:
            bc = self._eval_basis_crowding(features, short_enabled=short_enabled)
            if bc is not None:
                candidates.append(bc)

        if "funding_crowding" in allowed:
            fc = self._eval_funding_crowding(features, short_enabled=short_enabled)
            if fc is not None:
                candidates.append(fc)

        return candidates

    @staticmethod
    def _select_best_thesis(
        candidates: List[ThesisVerdict],
        *,
        pos_size: float,
        regime: str,
    ) -> ThesisVerdict:
        if not candidates:
            return ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=["thesis_no_rule_fired", f"regime={regime}"],
                thesis_type="flat",
            )

        ranked = sorted(candidates, key=lambda v: float(v.confidence), reverse=True)
        best = ranked[0]
        if len(ranked) >= 2:
            runner = ranked[1]
            conf_delta = abs(float(best.confidence) - float(runner.confidence))
            best_is_buy = str(best.signal).upper() in ("BUY", "STRONG_BUY")
            runner_is_buy = str(runner.signal).upper() in ("BUY", "STRONG_BUY")
            if conf_delta < 0.05 and best_is_buy != runner_is_buy:
                return ThesisVerdict(
                    signal="HOLD",
                    confidence=0.0,
                    position_size=0.0,
                    reason_codes=[
                        "thesis_direction_conflict",
                        f"best={best.signal}",
                        f"runner={runner.signal}",
                    ],
                    thesis_type="flat",
                )

        best.position_size = pos_size
        h_bars = thesis_intended_forward_bars(best.thesis_type)
        best.intended_horizon_bars = h_bars
        best.horizon_minutes = forward_bars_to_minutes(h_bars)
        return best

    @staticmethod
    def _apply_price_band_veto(
        verdict: ThesisVerdict,
        market_context: Dict[str, Any],
    ) -> ThesisVerdict:
        """Downgrade entry signals near exchange price-band limits."""
        sig = str(verdict.signal or "HOLD").upper()
        if sig not in _ENTRY_SIGNALS:
            return verdict
        prox = market_context.get("price_band_proximity")
        if not isinstance(prox, dict):
            return verdict
        veto_pct = float(
            getattr(settings, "jacksparrow_v43_price_band_veto_pct", 0.5) or 0.5
        )
        dist_upper = float(prox.get("dist_upper_pct") or 999.0)
        dist_lower = float(prox.get("dist_lower_pct") or 999.0)
        if sig in ("BUY", "STRONG_BUY") and dist_upper < veto_pct:
            return ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=[
                    "thesis_price_band_upper_veto",
                    f"dist_upper_pct={dist_upper:.3f}",
                ],
                thesis_type="flat",
            )
        if sig in ("SELL", "STRONG_SELL") and dist_lower < veto_pct:
            return ThesisVerdict(
                signal="HOLD",
                confidence=0.0,
                position_size=0.0,
                reason_codes=[
                    "thesis_price_band_lower_veto",
                    f"dist_lower_pct={dist_lower:.3f}",
                ],
                thesis_type="flat",
            )
        return verdict

    def _eval_basis_crowding(
        self,
        features: Dict[str, Any],
        *,
        short_enabled: bool,
    ) -> Optional[ThesisVerdict]:
        basis_z = _feat(features, "basis_zscore")
        oi_z = _feat(features, "oi_zscore")
        basis_thr = float(
            getattr(settings, "jacksparrow_v43_crowding_basis_threshold", 2.0) or 2.0
        )
        oi_thr = float(getattr(settings, "jacksparrow_v43_crowding_oi_threshold", 1.0) or 1.0)
        if oi_z <= oi_thr:
            return None
        if basis_z > basis_thr:
            if not short_enabled:
                return None
            conf = min(0.88, 0.6 + 0.05 * min(basis_z - basis_thr, 4.0))
            return ThesisVerdict(
                signal="SELL",
                confidence=conf,
                position_size=0.0,
                reason_codes=[
                    "thesis_basis_crowding_short",
                    f"basis_zscore={basis_z:.2f}",
                    f"oi_zscore={oi_z:.2f}",
                ],
                thesis_type="basis_crowding",
            )
        if basis_z < -basis_thr:
            conf = min(0.88, 0.6 + 0.05 * min(-basis_z - basis_thr, 4.0))
            return ThesisVerdict(
                signal="BUY",
                confidence=conf,
                position_size=0.0,
                reason_codes=[
                    "thesis_basis_crowding_long",
                    f"basis_zscore={basis_z:.2f}",
                    f"oi_zscore={oi_z:.2f}",
                ],
                thesis_type="basis_crowding",
            )
        return None

    def _eval_funding_crowding(
        self,
        features: Dict[str, Any],
        *,
        short_enabled: bool,
    ) -> Optional[ThesisVerdict]:
        fxoi = _feat(features, "funding_x_oi")
        thr = float(getattr(settings, "jacksparrow_v43_crowding_funding_x_oi_threshold", 1.5) or 1.5)
        if abs(fxoi) <= thr:
            return None
        if fxoi > thr:
            if not short_enabled:
                return None
            return ThesisVerdict(
                signal="SELL",
                confidence=min(0.85, 0.62 + 0.03 * min(fxoi - thr, 5.0)),
                position_size=0.0,
                reason_codes=["thesis_funding_crowding_short", f"funding_x_oi={fxoi:.2f}"],
                thesis_type="funding_crowding",
            )
        return ThesisVerdict(
            signal="BUY",
            confidence=min(0.85, 0.62 + 0.03 * min(-fxoi - thr, 5.0)),
            position_size=0.0,
            reason_codes=["thesis_funding_crowding_long", f"funding_x_oi={fxoi:.2f}"],
            thesis_type="funding_crowding",
        )

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

    def _eval_breakout_short(
        self, features: Dict[str, Any], regime: str
    ) -> Optional[ThesisVerdict]:
        adx = _feat(features, "adx_14")
        di = _feat(features, "di_spread")
        vol_reg = _feat(features, "vol_regime", 1.0)
        h_trend = _feat(features, "h_trend")
        adx_min = float(getattr(settings, "agent_thesis_breakout_adx_min", 25.0) or 25.0)
        di_min = float(getattr(settings, "agent_thesis_breakout_di_min", 5.0) or 5.0)
        vol_min = float(getattr(settings, "agent_thesis_breakout_vol_regime_min", 1.1) or 1.1)

        if adx <= adx_min or di >= -di_min or vol_reg <= vol_min or h_trend >= 0:
            return None

        conf = min(0.92, 0.65 + 0.01 * min(adx - adx_min, 15))
        return ThesisVerdict(
            signal="SELL",
            confidence=conf,
            position_size=0.0,
            reason_codes=[
                "thesis_breakout_short",
                f"adx_14={adx:.2f}",
                f"di_spread={di:.2f}",
                f"regime={regime}",
            ],
            thesis_type="breakout",
        )

    def _eval_trend_continuation_short(
        self, features: Dict[str, Any], regime: str
    ) -> Optional[ThesisVerdict]:
        h1 = _feat(features, "h1_trend")
        h = _feat(features, "h_trend")
        rsi = _feat(features, "rsi_14", 50.0)
        hurst = _feat(features, "hurst_60", 0.5)
        rsi_short_lo = float(
            getattr(settings, "agent_thesis_trend_short_rsi_lo", 35.0) or 35.0
        )
        rsi_short_hi = float(
            getattr(settings, "agent_thesis_trend_short_rsi_hi", 58.0) or 58.0
        )
        hurst_min = float(getattr(settings, "agent_thesis_trend_hurst_min", 0.52) or 0.52)

        if (
            h1 >= 0
            or h >= 0
            or rsi < rsi_short_lo
            or rsi > rsi_short_hi
            or hurst < hurst_min
        ):
            return None

        conf = min(0.88, 0.6 + 0.15 * min(abs(h1) * 100, 1.0))
        return ThesisVerdict(
            signal="SELL",
            confidence=conf,
            position_size=0.0,
            reason_codes=[
                "thesis_trend_continuation_short",
                f"h1_trend={h1:.4f}",
                f"h_trend={h:.4f}",
                f"regime={regime}",
            ],
            thesis_type="trend_continuation",
        )

    def _eval_mean_reversion_short(self, features: Dict[str, Any]) -> Optional[ThesisVerdict]:
        rsi = _feat(features, "rsi_14", 50.0)
        bb = _feat(features, "bb_pos", 0.5)
        rsi_min = float(getattr(settings, "agent_thesis_mr_rsi_short_min", 68.0) or 68.0)
        bb_min = float(getattr(settings, "agent_thesis_mr_bb_pos_short_min", 0.85) or 0.85)

        if rsi < rsi_min or bb < bb_min:
            return None

        return ThesisVerdict(
            signal="SELL",
            confidence=0.62,
            position_size=0.0,
            reason_codes=[
                "thesis_mean_reversion_short",
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
