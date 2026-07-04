"""Validate multi-regime scenario fixtures load and meet score expectations."""

import json
from pathlib import Path

import pytest

from agent.core.entry_quality import evaluate_entry_quality
from agent.core.strategy_types import (
    MarketStructureSnapshot,
    MLValidationSnapshot,
    StrategyCandidate,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "regime_scenarios"


@pytest.mark.parametrize(
    "fixture_name",
    sorted(p.name for p in FIXTURE_DIR.glob("*.json")),
)
def test_regime_fixture_quality_expectations(fixture_name: str) -> None:
    raw = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
    structure_raw = raw.get("structure") or {}
    direction = raw.get("direction_bias", "LONG")
    strategy = StrategyCandidate(
        direction=direction,
        strength=0.7,
        signal=direction,
        thesis_type="breakout" if direction != "FLAT" else "flat",
        confidence=0.75,
    )
    ml_val = MLValidationSnapshot(
        expected_return=0.012 if direction == "LONG" else -0.012,
        threshold=0.005,
        short_threshold=0.005,
        regime=str(raw.get("regime") or "neutral"),
        final_long=direction == "LONG",
        final_short=direction == "SHORT",
    )
    structure = MarketStructureSnapshot(
        market_type=str(structure_raw.get("market_type") or "NEUTRAL"),
        regime=str(raw.get("regime") or "neutral"),
        liquidity_ok=bool(structure_raw.get("liquidity_ok", True)),
    )
    mc = {
        "regime": raw.get("regime"),
        "gate5_economic": {"pass": True},
        "features": raw.get("features") or {"spread_bps": 8.0, "hurst_60": 0.55},
    }
    result = evaluate_entry_quality(
        strategy=strategy,
        ml_validation=ml_val,
        structure=structure,
        ml_confirms=True,
        market_context=mc,
        collapse_rate=0.15,
    )
    if "expected_min_quality_score" in raw:
        assert result.quality_score >= float(raw["expected_min_quality_score"])
    if "expected_max_quality_score" in raw:
        assert result.quality_score <= float(raw["expected_max_quality_score"])
    if "expected_max_microstructure" in raw:
        assert result.dimensions.get("microstructure", 1.0) <= float(
            raw["expected_max_microstructure"]
        )
