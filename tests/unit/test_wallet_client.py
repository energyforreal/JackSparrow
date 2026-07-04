"""Tests for Delta wallet transaction client method."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DELTA_CLIENT_PATH = ROOT / "agent" / "data" / "delta_client.py"
spec = importlib.util.spec_from_file_location("delta_client_wallet", DELTA_CLIENT_PATH)
assert spec and spec.loader
delta_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta_module)
DeltaExchangeClient = delta_module.DeltaExchangeClient


@pytest.fixture(autouse=True)
def delta_settings(monkeypatch):
    settings_stub = SimpleNamespace(
        delta_exchange_base_url="https://cdn-ind.testnet.deltaex.org",
        delta_exchange_api_key="test-key",
        delta_exchange_api_secret="test-secret",
    )
    monkeypatch.setattr(delta_module, "settings", settings_stub)
    yield


@pytest.mark.asyncio
async def test_get_wallet_transactions_builds_params():
    client = DeltaExchangeClient()
    mock_request = AsyncMock(
        return_value={"success": True, "result": [], "meta": {"after": None}}
    )
    with patch.object(client, "_make_request", mock_request):
        await client.get_wallet_transactions(
            asset_ids="5",
            transaction_types="commission,funding",
            start_time=1700000000000000,
            end_time=1700086400000000,
            page_size=50,
            after="cursor_abc",
            before="cursor_xyz",
        )
    mock_request.assert_awaited_once_with(
        "GET",
        "/v2/wallet/transactions",
        params={
            "page_size": 50,
            "asset_ids": "5",
            "transaction_types": "commission,funding",
            "start_time": 1700000000000000,
            "end_time": 1700086400000000,
            "after": "cursor_abc",
            "before": "cursor_xyz",
        },
    )


@pytest.mark.asyncio
async def test_get_wallet_transactions_defaults_page_size():
    client = DeltaExchangeClient()
    mock_request = AsyncMock(return_value={"success": True, "result": []})
    with patch.object(client, "_make_request", mock_request):
        await client.get_wallet_transactions()
    _, kwargs = mock_request.call_args
    assert kwargs["params"]["page_size"] == 100
