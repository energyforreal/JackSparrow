"""Tests for Delta testnet-only runtime enforcement in agent Settings."""

from __future__ import annotations

import os

import pytest


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
    monkeypatch.setenv("DELTA_EXCHANGE_API_KEY", "test-key")
    monkeypatch.setenv("DELTA_EXCHANGE_API_SECRET", "test-secret")
    monkeypatch.setenv("DELTA_EXCHANGE_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
    monkeypatch.setenv("TRADING_MODE", "testnet")
    monkeypatch.setenv("DELTA_ENV", "india_testnet")
    monkeypatch.delenv("PAPER_TRADING_MODE", raising=False)


def test_enforce_testnet_runtime_accepts_valid_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    from agent.core.config import Settings

    s = Settings()
    assert s.trading_mode == "testnet"
    assert s.exchange_backend == "delta_live"
    assert s.delta_env == "india_testnet"


def test_enforce_testnet_runtime_rejects_paper_trading_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("PAPER_TRADING_MODE", "true")
    from agent.core.config import Settings

    with pytest.raises(ValueError, match="PAPER_TRADING_MODE is removed"):
        Settings()


def test_enforce_testnet_runtime_rejects_prod_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("DELTA_EXCHANGE_BASE_URL", "https://api.india.delta.exchange")
    from agent.core.config import Settings

    with pytest.raises(ValueError, match="not an allowed Delta testnet host"):
        Settings()


def test_exchange_backend_rejects_delta_paper_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("EXCHANGE_BACKEND", "delta_paper_sim")
    from agent.core.config import Settings

    with pytest.raises(ValueError, match="delta_paper_sim is removed"):
        Settings()


def test_trading_mode_paper_coerced_to_testnet(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("TRADING_MODE", "paper")
    from agent.core.config import Settings

    s = Settings()
    assert s.trading_mode == "testnet"
