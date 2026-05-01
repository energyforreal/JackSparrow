"""Adaptive controller orchestration smoke tests."""

import pytest


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", False, raising=False)
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert out.get("reason") == "disabled"


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_none_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", True, raising=False)
    monkeypatch.setattr(
        config.settings, "adaptive_labeled_data_source", "none", raising=False
    )
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert "none" in str(out.get("reason", ""))
