"""Concurrency tests for JackSparrowV43Node bundle lifecycle locking."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
from agent.models.mcp_model_node import MCPModelPrediction, MCPModelRequest


def _make_node() -> JackSparrowV43Node:
    node = JackSparrowV43Node(
        model_name="jacksparrow_v43_BTCUSD",
        model_version="v43-test",
        metadata_path=Path("metadata_v43.json"),
        feature_names=["feat_a"],
    )
    node._artifact_path = Path("model_artifact_v43.pkl")
    return node


@pytest.mark.asyncio
async def test_concurrent_initialize_loads_bundle_once() -> None:
    node = _make_node()
    load_calls = 0

    def counted_load() -> None:
        nonlocal load_calls
        load_calls += 1
        node._initialized = True

    with patch.object(node, "_load_bundle_into_state", side_effect=counted_load):
        await asyncio.gather(*(node.initialize() for _ in range(5)))

    assert load_calls == 1
    assert node._initialized is True


@pytest.mark.asyncio
async def test_predict_emits_phase_timing_metadata() -> None:
    node = _make_node()
    node._initialized = True

    request = MCPModelRequest(
        request_id="phase-timing-test",
        features=[],
        context={},
        require_explanation=False,
    )

    fake_pred = MCPModelPrediction(
        model_name=node.model_name,
        model_version=node.model_version,
        prediction=0.1,
        confidence=0.5,
        reasoning="test",
        features_used=[],
        feature_importance={},
        computation_time_ms=1.0,
        health_status="healthy",
        context={},
    )

    with patch.object(node, "_reload_if_stale_locked"):
        with patch.object(node, "_sync_predict_impl", return_value=fake_pred):
            prediction = await node.predict(request)

    timings = (prediction.context or {}).get("predict_phase_timings_ms")
    assert isinstance(timings, dict)
    assert "bundle_ready_ms" in timings
    assert "lock_wait_ms" in timings
    assert "inference_ms" in timings
