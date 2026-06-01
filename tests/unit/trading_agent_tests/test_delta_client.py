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
DeltaExchangeWebSocketClient = delta_module.DeltaExchangeWebSocketClient
DeltaExchangeError = delta_module.DeltaExchangeError


@pytest.fixture(autouse=True)
def delta_settings(monkeypatch):
    """Provide stub configuration for DeltaExchangeClient."""
    settings_stub = SimpleNamespace(
        delta_exchange_base_url="https://api.india.delta.exchange",
        delta_exchange_api_key="test-key",
        delta_exchange_api_secret="test-secret",
        product_id=84,
    )
    monkeypatch.setattr(delta_module, "settings", settings_stub)
    yield


def test_build_headers_delete_payload_matches_compact_json(monkeypatch):
    monkeypatch.setattr(delta_module.time, "time", lambda: 1700000000.0)
    client = DeltaExchangeClient()
    data = {"id": 123, "product_id": 84}
    headers = client._build_headers(
        method="DELETE",
        endpoint="/v2/orders",
        params=None,
        data=data,
    )
    payload = client._serialize_payload(data, method="DELETE")
    expected_message = f"DELETE1700000000/v2/orders{payload}"
    expected_signature = hmac.new(
        b"test-secret", expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert headers["signature"] == expected_signature


@pytest.mark.asyncio
async def test_place_order_rejects_fractional_size():
    client = DeltaExchangeClient()
    with pytest.raises(DeltaExchangeError, match="whole number"):
        await client.place_order("BTCUSD", "buy", 1.5, "MARKET")


@pytest.mark.asyncio
async def test_get_positions_requires_product_filter():
    client = DeltaExchangeClient()
    with pytest.raises(DeltaExchangeError, match="requires product"):
        await client.get_positions()


def test_build_headers_post_payload_matches_compact_json(monkeypatch):
    monkeypatch.setattr(delta_module.time, "time", lambda: 1700000000.0)
    client = DeltaExchangeClient()
    data = {
        "product_id": 84,
        "size": 1,
        "side": "buy",
        "order_type": "market_order",
    }
    headers = client._build_headers(
        method="POST",
        endpoint="/v2/orders",
        params=None,
        data=data,
    )
    payload = client._serialize_payload(data, method="POST")
    expected_message = f"POST1700000000/v2/orders{payload}"
    expected_signature = hmac.new(
        b"test-secret", expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert headers["signature"] == expected_signature
    assert " " not in payload


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
    assert headers["timestamp"] == "1700000000"

    query = client._build_query_string({"symbol": "BTCUSD"})
    expected_message = f"GET1700000000/v2/tickers/BTCUSD{query}"
    expected_signature = hmac.new(
        b"test-secret", expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert headers["signature"] == expected_signature


def test_is_public_market_endpoint():
    assert DeltaExchangeClient._is_public_market_endpoint("/v2/history/candles")
    assert DeltaExchangeClient._is_public_market_endpoint("/v2/tickers/BTCUSD")
    assert DeltaExchangeClient._is_public_market_endpoint("/v2/l2orderbook/BTCUSD")
    assert not DeltaExchangeClient._is_public_market_endpoint("/v2/positions/margined")


def test_extract_client_ip_from_error():
    body = json.dumps(
        {
            "error": {
                "code": "ip_not_whitelisted_for_api_key",
                "context": {"client_ip": "203.0.113.10"},
            },
            "success": False,
        }
    )
    assert DeltaExchangeClient._extract_client_ip_from_error(body) == "203.0.113.10"


def test_latch_ip_restriction_opens_circuit_breaker():
    client = DeltaExchangeClient()
    client.circuit_breaker.state = delta_module.CircuitBreakerState.CLOSED
    client._latch_auth_blocked("ip_restriction", client_ip="203.0.113.10")
    assert client.circuit_breaker.state == delta_module.CircuitBreakerState.OPEN
    assert client._auth_blocked_client_ip == "203.0.113.10"


@pytest.mark.asyncio
async def test_get_ticker_uses_public_request(monkeypatch):
    client = DeltaExchangeClient()
    calls = []

    async def fake_public(method, endpoint, params=None):
        calls.append((method, endpoint, params))
        return {"success": True, "result": {"close": 1.0}}

    monkeypatch.setattr(client, "_make_public_request", fake_public)
    out = await client.get_ticker("BTCUSD")
    assert out["success"] is True
    assert calls == [("GET", "/v2/tickers/BTCUSD", None)]


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


def test_websocket_auth_payload_uses_live_path_and_seconds(monkeypatch):
    monkeypatch.setattr(delta_module.time, "time", lambda: 1700000000.0)
    ws_client = DeltaExchangeWebSocketClient(
        api_key="test-key",
        api_secret="test-secret",
        base_url="wss://socket-ind.testnet.deltaex.org",
    )
    auth = ws_client.build_websocket_auth_payload()
    assert auth["type"] == "key-auth"
    assert auth["payload"]["api-key"] == "test-key"
    assert auth["payload"]["timestamp"] == "1700000000"
    expected_message = "GET1700000000/live"
    expected_signature = hmac.new(
        b"test-secret", expected_message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert auth["payload"]["signature"] == expected_signature

