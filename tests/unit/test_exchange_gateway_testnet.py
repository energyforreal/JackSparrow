"""Unit tests for testnet-only exchange gateway factory."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
os.environ.setdefault("TRADING_MODE", "testnet")
os.environ.setdefault("DELTA_ENV", "india_testnet")

from agent.core.exchange_gateway import (
    DeltaLiveExchangeGateway,
    build_exchange_gateway,
)


@pytest.mark.asyncio
async def test_build_exchange_gateway_returns_live_adapter():
    client = object()

    async def _close(_symbol: str):
        return None

    gateway = build_exchange_gateway(
        delta_client=client,
        position_reader=lambda: {},
        close_position_cb=_close,
    )
    assert isinstance(gateway, DeltaLiveExchangeGateway)
    assert gateway._delta_client is client
