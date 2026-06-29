"""Market Understanding Engine — derives objective market facts from rolling history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.market_structure import classify_market_structure
from agent.core.strategy_types import MarketStructureSnapshot
from agent.intelligence.market_types import MarketStateSnapshot

logger = structlog.get_logger()


def _feat(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _trend_from_features(features: Dict[str, Any]) -> str:
    h1 = _feat(features, "h1_trend", 0.0)
    h_trend = _feat(features, "h_trend", 0.0)
    ema_bias = _feat(features, "ema200_bias", 0.0)
    score = h1 * 0.4 + h_trend * 0.35 + ema_bias * 0.25
    if score > 0.15:
        return "bullish"
    if score < -0.15:
        return "bearish"
    return "neutral"


def _trend_strength_label(features: Dict[str, Any], structure: MarketStructureSnapshot) -> str:
    adx = _feat(features, "adx_14")
    hurst = _feat(features, "hurst_60", 0.5)
    if structure.market_type == "TRENDING" and adx >= 28 and hurst >= 0.55:
        return "strong"
    if adx >= 22 or structure.market_type == "TRENDING":
        return "moderate"
    return "weak"


def _momentum_label(features: Dict[str, Any], prev_momentum: Optional[str]) -> str:
    rsi_mom = _feat(features, "rsi_mom")
    mom_accel = _feat(features, "mom_accel")
    trend_mom = _feat(features, "trend_mom")
    composite = rsi_mom * 0.3 + mom_accel * 0.35 + trend_mom * 0.35
    if composite > 0.05:
        return "increasing"
    if composite < -0.05:
        return "decreasing"
    return prev_momentum or "flat"


def _volatility_label(features: Dict[str, Any]) -> str:
    vol_regime = _feat(features, "vol_regime", 1.0)
    atr_pct = _feat(features, "atr_pct")
    if vol_regime > 1.1 or atr_pct > 0.012:
        return "expanding"
    if vol_regime < 0.9 and atr_pct < 0.006:
        return "compressing"
    return "stable"


def _liquidity_label(
    features: Dict[str, Any],
    structure: MarketStructureSnapshot,
) -> str:
    spread = _feat(features, "spread_bps")
    spread_max = float(getattr(settings, "agent_thesis_max_spread_bps", 50.0) or 50.0)
    if "structure_spread_high" in (structure.reason_codes or []):
        return "stressed"
    if spread > spread_max * 0.7:
        return "thin"
    return "healthy"


def _breakout_status(
    features: Dict[str, Any],
    thesis_type: str,
    failed_breakout_count: int,
) -> str:
    if failed_breakout_count >= 2:
        return "failed"
    breakout_score = _feat(features, "breakout_score", 0.5)
    vol_exp = _feat(features, "vol_expansion", 0.0)
    if thesis_type == "breakout" and breakout_score >= 0.65 and vol_exp > 0:
        return "confirmed"
    if breakout_score >= 0.5 and vol_exp >= 0:
        return "forming"
    return "none"


def _retest_status(features: Dict[str, Any], breakout_status: str) -> str:
    if breakout_status != "confirmed":
        return "none"
    pullback_depth = _feat(features, "pullback_depth", 0.0)
    if pullback_depth > 0.02:
        return "pending"
    if pullback_depth > 0 and pullback_depth <= 0.02:
        return "successful"
    return "none"


def _mtf_roles(features: Dict[str, Any], trend: str) -> Dict[str, str]:
    h1 = _feat(features, "h1_trend")
    m15 = _feat(features, "m15_trend", _feat(features, "h_trend"))
    m5 = _feat(features, "trend_mom")
    roles: Dict[str, str] = {}
    if abs(h1) > 0.1:
        roles["h1"] = "context_bullish" if h1 > 0 else "context_bearish"
    else:
        roles["h1"] = "context_neutral"
    if abs(m15) > 0.08:
        roles["m15"] = "setup_aligned" if (m15 > 0) == (trend == "bullish") else "setup_counter"
    else:
        roles["m15"] = "setup_neutral"
    roles["m5"] = "execution_ready" if abs(m5) > 0.05 else "execution_wait"
    return roles


def _structural_confidence_label(
    trend_strength: str,
    liquidity: str,
    breakout_status: str,
    momentum: str,
) -> str:
    score = 0
    if trend_strength == "strong":
        score += 2
    elif trend_strength == "moderate":
        score += 1
    if liquidity == "healthy":
        score += 1
    if breakout_status == "confirmed":
        score += 2
    elif breakout_status == "forming":
        score += 1
    if momentum == "increasing":
        score += 1
    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def _direction_bias(
    trend: str,
    breakout_status: str,
    thesis_signal: str,
) -> str:
    sig = str(thesis_signal or "HOLD").upper()
    if sig in ("LONG", "STRONG_LONG"):
        return "LONG"
    if sig in ("SHORT", "STRONG_SHORT"):
        return "SHORT"
    if trend == "bullish" and breakout_status in ("confirmed", "forming"):
        return "LONG"
    if trend == "bearish" and breakout_status in ("confirmed", "forming"):
        return "SHORT"
    return "HOLD"


def _scan_trend_age(
    features_history: Optional[List[Dict[str, Any]]],
    current_trend: str,
) -> int:
    """Count consecutive closed bars with same trend direction."""
    if not features_history:
        return 1
    age = 1
    for row in reversed(features_history[:-1]):
        t = _trend_from_features(row)
        if t == current_trend and current_trend != "neutral":
            age += 1
        else:
            break
    return age


def features_history_from_matrix(
    df_feat: Any,
    *,
    lookback: int = 30,
) -> List[Dict[str, Any]]:
    """Build per-bar feature dict history from feature matrix (excludes open bar)."""
    try:
        import pandas as pd
    except ImportError:
        return []
    if df_feat is None or not isinstance(df_feat, pd.DataFrame) or df_feat.empty:
        return []
    if len(df_feat) < 2:
        return []
    end_idx = len(df_feat) - 1
    start_idx = max(0, end_idx - int(lookback))
    rows: List[Dict[str, Any]] = []
    for _, row in df_feat.iloc[start_idx:end_idx].iterrows():
        feats: Dict[str, Any] = {}
        for k, v in row.items():
            try:
                fv = float(v)
                if fv == fv:
                    feats[str(k)] = fv
            except (TypeError, ValueError):
                continue
        if feats:
            rows.append(feats)
    return rows


class MarketUnderstandingEngine:
    """Derives MarketStateSnapshot from features, structure, and history."""

    def __init__(self) -> None:
        self._prev_momentum: Dict[str, str] = {}

    def evaluate(
        self,
        *,
        symbol: str,
        bar_index: int,
        features: Dict[str, Any],
        regime: str,
        structure: Optional[MarketStructureSnapshot] = None,
        thesis_signal: str = "HOLD",
        thesis_type: str = "flat",
        failed_breakout_count: int = 0,
        features_history: Optional[List[Dict[str, Any]]] = None,
        contract_state: Any = None,
    ) -> MarketStateSnapshot:
        """Build objective market state snapshot for one closed bar."""
        if structure is None:
            structure = classify_market_structure(
                features,
                v43_regime=regime,
                contract_state=contract_state,
            )

        sym = str(symbol).strip().upper()
        trend = _trend_from_features(features)
        trend_strength = _trend_strength_label(features, structure)
        prev_mom = self._prev_momentum.get(sym)
        momentum = _momentum_label(features, prev_mom)
        self._prev_momentum[sym] = momentum

        breakout_status = _breakout_status(features, thesis_type, failed_breakout_count)
        retest_status = _retest_status(features, breakout_status)
        liquidity = _liquidity_label(features, structure)
        volatility = _volatility_label(features)
        mtf = _mtf_roles(features, trend)
        confidence = _structural_confidence_label(
            trend_strength, liquidity, breakout_status, momentum
        )
        direction_bias = _direction_bias(trend, breakout_status, thesis_signal)
        trend_age = _scan_trend_age(features_history, trend)

        snap = MarketStateSnapshot(
            symbol=sym,
            bar_index=bar_index,
            trend=trend,
            trend_strength=trend_strength,
            trend_age_candles=trend_age,
            momentum=momentum,
            breakout_status=breakout_status,
            retest_status=retest_status,
            structure=str(structure.market_type),
            liquidity=liquidity,
            volatility=volatility,
            regime=str(regime or "neutral"),
            confidence=confidence,
            mtf=mtf,
            direction_bias=direction_bias,
        )
        logger.info(
            "market_understanding_snapshot",
            symbol=sym,
            bar_index=bar_index,
            trend=trend,
            trend_strength=trend_strength,
            trend_age_candles=trend_age,
            momentum=momentum,
            breakout_status=breakout_status,
            retest_status=retest_status,
            liquidity=liquidity,
            volatility=volatility,
            confidence=confidence,
            direction_bias=direction_bias,
        )
        return snap


market_understanding_engine = MarketUnderstandingEngine()
