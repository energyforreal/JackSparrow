"""Tests for Delta Exchange client signing and error handling."""

import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DELTA_CLIENT_PATH = ROOT / "agent" / "data" / "delta_client.py"
spec = importlib.util.spec_from_file_location("delta_client_module", DELTA_CLIENT_PATH)
assert spec and spec.loader
delta_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delta_module)
DeltaExchangeClient = delta_module.DeltaExchangeClient
DeltaExchangeError = delta_module.DeltaExchangeError


@pytest.fixture(autouse=True)
def delta_settings(monkeypatch):
    """Provide stub configuration for DeltaExchangeClient."""
    settings_stub = SimpleNamespace(
        delta_exchange_base_url="https://api.delta.exchange",
        delta_exchange_api_key="test-key",
        delta_exchange_api_secret="test-secret",
    )
    monkeypatch.setattr(delta_module, "settings", settings_stub)
    yield


def test_build_headers_generates_expected_signature(monkeypatch):
    monkeypatch.setattr(delta_module.time, "time", lambda: 1700000000.0)
    client = DeltaExchangeClient()

    headers = client._build_headers(
        method="GET",
        endpoint="/v2/tickers/BTCUSD",
        params={"symbol": "BTCUSD"},
        data=None,
    )

    assert headers["api-key"] == "test-key"
    assert headers["timestamp"] == "1700000000000"

    payload = json.dumps({"symbol": "BTCUSD"}, separators=(",", ":"), sort_keys=True)
    expected_message = f"{headers['timestamp']}GET/v2/tickers/BTCUSD{payload}"
    expected_signature = hmac.new(
        b"test-secret", expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert headers["signature"] == expected_signature


@pytest.mark.asyncio
async def test_make_request_raises_on_http_error(monkeypatch):
    client = DeltaExchangeClient()

    class DummyResponse:
        def __init__(self):
            self.status_code = 400
            self.text = "bad request"

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda timeout: DummyClient())

    with pytest.raises(DeltaExchangeError):
        await client._make_request("GET", "/v2/tickers/BTCUSD", params={}, data=None)

