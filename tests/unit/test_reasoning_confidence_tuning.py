import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.reasoning_engine import MCPReasoningEngine
from agent.learning import dynamic_thresholds


def test_extract_hold_bucket_maps_mtf_not_confirming_trend():
    bucket = MCPReasoningEngine._extract_hold_bucket(
        "HOLD - MTF entry not confirming trend (BUY)",
        ["entry confidence below minimum"],
    )
    assert bucket == "mtf_not_confirming_trend"


def test_extract_hold_bucket_maps_consensus_hold_band():
    bucket = MCPReasoningEngine._extract_hold_bucket(
        "HOLD - Mixed signals, waiting for clearer direction",
        ["reason=consensus_in_hold_band"],
    )
    assert bucket == "consensus_in_hold_band"


@pytest.mark.asyncio
async def test_apply_redis_hold_band_overrides_enforces_separation(monkeypatch):
    values = {"learning:mild_thresh": 0.28, "learning:strong_thresh": 0.30}

    async def fake_redis_get_float(key: str):
        return values.get(key)

    monkeypatch.setattr(dynamic_thresholds, "_redis_get_float", fake_redis_get_float)
    strong, mild = await dynamic_thresholds.apply_redis_hold_band_overrides(0.4, 0.18)
    assert mild == pytest.approx(0.28)
    assert strong >= mild + 0.05


@pytest.mark.asyncio
async def test_effective_min_confidence_threshold_clamps_redis_value(monkeypatch):
    async def fake_redis_get_float(_key: str):
        return 0.95

    monkeypatch.setattr(dynamic_thresholds, "_redis_get_float", fake_redis_get_float)
    out = await dynamic_thresholds.get_effective_min_confidence_threshold()
    assert out == pytest.approx(dynamic_thresholds.MIN_CONF_BOUNDS[1])
