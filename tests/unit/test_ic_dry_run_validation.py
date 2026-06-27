"""IC dry-run warmup must not require v43 frames or poison model health."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.core.mcp_orchestrator import MCPOrchestrator


class _FakeIcNode:
    model_type = "rule_based_intelligence"

    def __init__(self, initialized: bool = True) -> None:
        self._initialized = initialized

    async def get_health_status(self) -> dict:
        return {
            "status": "healthy" if self._initialized else "unknown",
            "initialized": self._initialized,
        }


@pytest.mark.asyncio
async def test_validate_models_dry_run_ic_checks_init_only() -> None:
    orchestrator = MCPOrchestrator()
    ic = _FakeIcNode(initialized=True)
    orchestrator.model_registry = MagicMock()
    orchestrator.model_registry.models = {"jacksparrow_ic_BTCUSD": ic}

    with patch.object(
        orchestrator.model_registry,
        "get_predictions",
        new_callable=AsyncMock,
    ) as mock_predict:
        ok = await orchestrator.validate_models_dry_run()

    assert ok is True
    mock_predict.assert_not_called()


@pytest.mark.asyncio
async def test_validate_models_dry_run_ic_not_initialized_fails() -> None:
    orchestrator = MCPOrchestrator()
    ic = _FakeIcNode(initialized=False)
    orchestrator.model_registry = MagicMock()
    orchestrator.model_registry.models = {"jacksparrow_ic_BTCUSD": ic}

    ok = await orchestrator.validate_models_dry_run()

    assert ok is False
