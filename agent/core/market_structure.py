"""Market structure intelligence — independent of ML model outputs."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent.core.config import settings
from agent.core.strategy_types import MarketStructureSnapshot
from agent.core.v43_contract_state import ContractStateSnapshot


def _feat(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = features.get(key)
    if raw is None:
        return default
    try:
        v = float(raw)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _normalize_v43_regime(regime: Optional[str]) -> str:
    r = str(regime or "neutral").strip().lower()
    if r in ("crisis", "trending", "ranging", "neutral", "unknown"):
        return r
    return "neutral"


def classify_market_structure(
    features: Dict[str, Any],
    *,
    v43_regime: Optional[str] = None,
    contract_state: Optional[ContractStateSnapshot] = None,
) -> MarketStructureSnapshot:
    """Classify market from closed-bar features (deterministic, no ML)."""
    reg = _normalize_v43_regime(v43_regime)
    adx = _feat(features, "adx_14")
    atr_pct = _feat(features, "atr_pct")
    vol_regime = _feat(features, "vol_regime", 1.0)
    hurst = _feat(features, "hurst_60", 0.5)

    reasons: list[str] = []
    chop_atr_max = float(
        getattr(settings, "agent_structure_chop_atr_pct_max", 0.003) or 0.003
    )
    low_vol_regime_max = float(
        getattr(settings, "agent_structure_low_vol_regime_max", 0.85) or 0.85
    )
    trending_adx_min = float(
        getattr(settings, "agent_structure_trending_adx_min", 22.0) or 22.0
    )

    chop_market = atr_pct > 0 and atr_pct < chop_atr_max and vol_regime < low_vol_regime_max
    if chop_market:
        reasons.append("structure_chop_low_vol")

    spread_proxy = _feat(features, "spread_bps", 0.0)
    spread_max = float(getattr(settings, "agent_thesis_max_spread_bps", 50.0) or 50.0)
    liquidity_ok = spread_proxy <= 0 or spread_proxy <= spread_max
    if contract_state is not None and contract_state.impact_size > 0:
        if spread_proxy > spread_max and spread_proxy > 0:
            liquidity_ok = False
    if not liquidity_ok:
        reasons.append(f"structure_spread_high={spread_proxy:.1f}")

    if contract_state is not None and not contract_state.is_operational:
        liquidity_ok = False
        reasons.append("structure_contract_not_operational")

    if reg == "crisis":
        market_type = "CRISIS"
        reasons.append("structure_crisis_regime")
    elif chop_market:
        market_type = "LOW_VOL"
    elif adx >= trending_adx_min and hurst >= 0.52:
        market_type = "TRENDING"
        reasons.append("structure_trending")
    elif reg == "ranging" or (adx < trending_adx_min and vol_regime < 1.05):
        market_type = "RANGING"
        reasons.append("structure_ranging")
    else:
        market_type = "NEUTRAL"

    return MarketStructureSnapshot(
        market_type=market_type,
        regime=reg,
        adx=adx,
        atr_pct=atr_pct,
        vol_regime=vol_regime,
        liquidity_ok=liquidity_ok,
        chop_market=chop_market,
        reason_codes=reasons,
    )
