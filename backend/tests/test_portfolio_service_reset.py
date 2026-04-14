"""Unit tests for paper portfolio reset helpers."""

import pytest
from unittest.mock import AsyncMock

from backend.services.portfolio_service import PortfolioService


@pytest.mark.asyncio
async def test_delete_all_trades_and_positions_executes_two_deletes():
    svc = PortfolioService()
    db = AsyncMock()
    await svc.delete_all_trades_and_positions(db)
    assert db.execute.await_count == 2
