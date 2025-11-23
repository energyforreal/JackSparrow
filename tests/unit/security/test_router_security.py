"""Ensure sensitive routers enforce authentication dependencies."""

import os
import sys
import types

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("API_KEY", "test-api-key")

if "jose" not in sys.modules:
    jose_module = types.ModuleType("jose")

    class _JWTError(Exception):
        """Test stub for jose.JWTError."""

    def _decode(token, key, algorithms=None):
        return {}

    jose_module.JWTError = _JWTError
    jose_module.jwt = types.SimpleNamespace(decode=_decode)
    sys.modules["jose"] = jose_module

from backend.api.middleware.auth import require_auth
from backend.api.routes import admin, trading, portfolio


def _dependency_callables(router):
    return [dependency.dependency for dependency in router.dependencies]


def test_trading_router_requires_auth():
    assert require_auth in _dependency_callables(trading.router)


def test_portfolio_router_requires_auth():
    assert require_auth in _dependency_callables(portfolio.router)


def test_admin_router_requires_auth():
    assert require_auth in _dependency_callables(admin.router)

