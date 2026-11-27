"""Health score when model serving and model nodes are off the decision path."""

import pytest

from backend.api.routes.health import (
    NON_MODEL_WEIGHT,
    check_model_nodes_health,
    decision_path_uses_models,
    finalize_health_score,
)


def test_algorithmic_path_does_not_use_models() -> None:
    assert decision_path_uses_models("algorithmic") is False
    assert decision_path_uses_models(" Algorithmic ") is False
    assert decision_path_uses_models("mtf_fusion") is True
    assert decision_path_uses_models("forecast_30m") is True
    assert decision_path_uses_models(None) is True


def test_full_non_model_stack_scores_one_when_models_are_omitted() -> None:
    """database+redis+agent+feature+delta+reasoning == 0.75, scaled to 1.0."""
    assert finalize_health_score(NON_MODEL_WEIGHT, include_models=False) == 1.0


def test_model_weight_still_counts_on_a_model_path() -> None:
    assert finalize_health_score(NON_MODEL_WEIGHT, include_models=True) == 0.75
    assert finalize_health_score(1.0, include_models=True) == 1.0


def test_redis_down_is_rescaled_without_models() -> None:
    # 0.75 - redis 0.05 = 0.70, then / 0.75.
    assert finalize_health_score(0.70, include_models=False) == 0.933


def test_score_stays_inside_unit_interval() -> None:
    assert finalize_health_score(0.0, include_models=False) == 0.0
    assert finalize_health_score(2.0, include_models=True) == 1.0


@pytest.mark.asyncio
async def test_failed_discovery_stays_down_when_agent_is_up() -> None:
    """An empty registry after failed loads is down, not inferred up."""
    status = await check_model_nodes_health(
        {
            "available": True,
            "model_nodes": {
                "status": "down",
                "healthy_models": 0,
                "total_models": 0,
                "note": "Model discovery attempted but no models loaded successfully.",
                "discovery": {"discovery_attempted": True, "failed_models": 5},
            },
        }
    )
    assert status.status == "down"
    assert status.details is not None
    assert "no models loaded" in str(status.details.get("note", "")).lower()


@pytest.mark.asyncio
async def test_up_with_zero_models_is_not_reported_up() -> None:
    status = await check_model_nodes_health(
        {
            "available": True,
            "model_nodes": {
                "status": "up",
                "healthy_models": 0,
                "total_models": 0,
                "discovery": {"failed_models": 5},
            },
        }
    )
    assert status.status == "down"
