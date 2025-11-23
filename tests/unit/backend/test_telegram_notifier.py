"""Tests for Telegram notifier."""

import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = PROJECT_ROOT / "backend" / "notifications" / "telegram.py"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

backend_module = ModuleType("backend")
core_module = ModuleType("backend.core")
config_module = ModuleType("backend.core.config")
config_module.settings = SimpleNamespace(
    telegram_bot_token=None,
    telegram_chat_id=None,
)
backend_module.core = core_module
core_module.config = config_module
sys.modules["backend"] = backend_module
sys.modules["backend.core"] = core_module
sys.modules["backend.core.config"] = config_module

SPEC = importlib.util.spec_from_file_location(
    "project_backend.notifications.telegram", MODULE_PATH
)
telegram_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(telegram_module)  # type: ignore[attr-defined]
notifications_module = ModuleType("backend.notifications")
notifications_module.telegram = telegram_module
backend_module.notifications = notifications_module
sys.modules["backend.notifications"] = notifications_module
sys.modules.setdefault("backend.notifications.telegram", telegram_module)
TelegramNotifier = telegram_module.TelegramNotifier


class MockResponse:
    """Simple HTTPX-like response."""

    def __init__(self, status_code=200, payload=None, text="mock"):
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = text

    def json(self):
        return self._payload


def patch_http_client(monkeypatch, response: MockResponse):
    """Patch httpx.AsyncClient to return provided response."""

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return response

    monkeypatch.setattr(
        "backend.notifications.telegram.httpx.AsyncClient",
        lambda *args, **kwargs: _MockClient(),
    )


@pytest.mark.asyncio
async def test_send_message_disabled():
    """Sending a message without configuration should short-circuit."""
    notifier = TelegramNotifier(bot_token=None, chat_id=None)
    assert notifier.enabled is False

    result = await notifier.send_message("hello world")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_success(monkeypatch):
    """Successful HTTP call returns True."""
    patch_http_client(monkeypatch, MockResponse(status_code=200, payload={"ok": True}))

    notifier = TelegramNotifier(bot_token="token", chat_id="123")
    result = await notifier.send_message("hello")

    assert result is True


@pytest.mark.asyncio
async def test_send_message_failure(monkeypatch):
    """HTTP errors are handled and return False."""
    patch_http_client(
        monkeypatch,
        MockResponse(status_code=400, payload={"ok": False, "description": "bad"}),
    )

    notifier = TelegramNotifier(bot_token="token", chat_id="123")
    result = await notifier.send_message("hello")

    assert result is False


@pytest.mark.asyncio
async def test_notify_trade_execution(monkeypatch):
    """Trade execution notification delegates to send_message."""
    notifier = TelegramNotifier(bot_token="token", chat_id="123")
    mocked = AsyncMock(return_value=True)
    monkeypatch.setattr(notifier, "send_message", mocked)

    payload = {
        "order_id": "abc",
        "pnl": 1.23,
        "status": "EXECUTED",
    }

    result = await notifier.notify_trade_execution(
        symbol="BTCUSD",
        side="BUY",
        quantity=0.5,
        price=27000.0,
        order_type="MARKET",
        result=payload,
    )

    assert result is True
    mocked.assert_awaited_once()
    args, kwargs = mocked.await_args
    assert "Trade Executed" in args[0]

