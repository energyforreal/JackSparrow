"""Unit tests for MarketIntelligence diff engine."""

from __future__ import annotations

from datetime import datetime, timezone

from agent.core.strategy_types import MarketStructureSnapshot
from agent.intelligence.market_intelligence import MarketIntelligence
from agent.intelligence.market_intelligence_diff import diff_market_intelligence


def _intel(
    *,
    adx: float = 20.0,
    hurst: float = 0.5,
    confidence: float = 0.5,
    bar_index: int = 100,
) -> MarketIntelligence:
    structure = MarketStructureSnapshot(
        market_type="NEUTRAL",
        regime="neutral",
        liquidity_ok=True,
    )
    closed_feats = {
        "adx_14": adx,
        "hurst_60": hurst,
        "atr_pct": 0.01,
        "vol_regime": 1.0,
    }
    return MarketIntelligence.from_cycle(
        symbol="BTCUSD",
        bar_index=bar_index,
        closed_feats=closed_feats,
        structure=structure,
        thesis_verdict={"signal": "HOLD", "confidence": confidence},
        timestamp=datetime.now(timezone.utc),
    )


def test_diff_initial_snapshot_is_material() -> None:
    current = _intel()
    diff = diff_market_intelligence(None, current)
    assert diff.changed is True
    assert "initial_snapshot" in diff.reasons


def test_diff_regime_flip_is_material() -> None:
    prev = _intel(adx=20.0, hurst=0.5)
    curr = _intel(adx=30.0, hurst=0.60)
    assert prev.regime == "neutral"
    assert curr.regime == "trending"
    diff = diff_market_intelligence(prev, curr)
    assert diff.changed is True
    assert any("regime" in r for r in diff.reasons)


def test_diff_small_confidence_delta_not_material_alone() -> None:
    prev = _intel(confidence=0.50)
    curr = _intel(confidence=0.52)
    curr.bar_index = prev.bar_index
    diff = diff_market_intelligence(prev, curr)
    assert diff.changed is False
