"""Test hard-fail when Delta testnet is unreachable (no DB fallback)."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")

from backend.services.testnet_portfolio_service import (
    TestnetExchangeUnavailableError,
    TestnetPortfolioService,
)


@pytest.mark.asyncio
async def test_get_portfolio_summary_raises_when_exchange_unavailable():
    svc = TestnetPortfolioService()
    with patch.object(svc, "fetch_exchange_snapshot", new=AsyncMock(return_value=None)):
        with pytest.raises(TestnetExchangeUnavailableError):
            await svc.get_portfolio_summary(db=AsyncMock())
