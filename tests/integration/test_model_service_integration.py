"""
Integration tests for model-service client, prediction cache, and prediction audit.

Covers: model-service healthy path, timeout/fallback behavior, Redis prediction cache
keys, and prediction_audit persistence (model sanity). Uses mocks for HTTP and
optional Redis/DB so tests run in CI without live services.
"""

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("DELTA_EXCHANGE_API_KEY", "test-key")
os.environ.setdefault("DELTA_EXCHANGE_API_SECRET", "test-secret")

from backend.services.model_service import ModelService, _float_to_signal


class TestModelServiceClient:
    """Model-serving HTTP client: healthy path and timeout/fallback."""

    @pytest.mark.asyncio
    async def test_get_prediction_success_returns_normalized_response(self):
        """When model-serving returns 200, response is normalized with source=model_service."""
        service = ModelService(base_url="http://test:8002", timeout=5.0, retries=0)
        mock_response = {
            "symbol": "BTCUSD",
            "predictions": {
                "xgboost_BTCUSD_15m": {"prediction": 0.5, "confidence": 0.8},
            },
            "consensus_signal": 0.5,
            "confidence": 0.8,
            "timestamp": "2025-01-15T12:00:00Z",
            "computation_time_ms": 120.0,
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            mock_client.__aexit__.return_value = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await service.get_prediction(symbol="BTCUSD")
            assert result is not None
            assert result.get("success") is True
            data = result.get("data", {})
            assert data.get("source") == "model_service"
            assert data.get("signal") in ("BUY", "HOLD", "STRONG_BUY")
            assert data.get("confidence") == 0.8
            assert "inference_latency_ms" in data or "computation_time_ms" in data
            assert len(data.get("model_predictions", [])) >= 1

    @pytest.mark.asyncio
    async def test_get_prediction_timeout_returns_none(self):
        """When model-serving times out, get_prediction returns None (caller can fallback)."""
        import httpx
        service = ModelService(base_url="http://test:8002", timeout=0.1, retries=0)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("timeout")
            )
            mock_client.__aexit__.return_value = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await service.get_prediction(symbol="BTCUSD")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_health_returns_up_when_models_list_ok(self):
        """get_health returns status up when /api/v1/models returns 200."""
        service = ModelService(base_url="http://test:8002")
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"models": [{"name": "xgboost_BTCUSD_15m"}], "count": 1}
            mock_resp.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            mock_client.__aexit__.return_value = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            health = await service.get_health()
            assert health.get("status") == "up"
            assert health.get("details", {}).get("model_count") == 1


class TestFloatToSignal:
    """Discrete signal mapping from continuous prediction."""

    def test_hold_for_small_values(self):
        assert _float_to_signal(0.1) == "HOLD"
        assert _float_to_signal(-0.15) == "HOLD"

    def test_buy_strong_buy(self):
        assert _float_to_signal(0.25) == "BUY"
        assert _float_to_signal(0.65) == "STRONG_BUY"

    def test_sell_strong_sell(self):
        assert _float_to_signal(-0.25) == "SELL"
        assert _float_to_signal(-0.65) == "STRONG_SELL"


class TestPredictionAuditModel:
    """PredictionAudit model and migration sanity."""

    def test_prediction_audit_model_import_and_fields(self):
        """PredictionAudit can be imported and has expected columns."""
        from backend.core.database import PredictionAudit
        # Instantiate with minimal fields (request_id, symbol required by schema)
        audit = PredictionAudit(
            request_id="test-req-1",
            symbol="BTCUSD",
            confidence=Decimal("0.85"),
            latency_ms=Decimal("120.5"),
            source="model_service",
        )
        assert audit.request_id == "test-req-1"
        assert audit.symbol == "BTCUSD"
        assert audit.source == "model_service"
        assert float(audit.confidence) == 0.85
        assert float(audit.latency_ms) == 120.5


class TestPredictionCacheKeys:
    """Redis prediction cache and model health key usage."""

    def test_prediction_cache_key_format(self):
        """Prediction cache uses key prediction:{symbol}."""
        from backend.core.redis import PREDICTION_CACHE_PREFIX, MODEL_HEALTH_KEY
        assert PREDICTION_CACHE_PREFIX == "prediction:"
        assert MODEL_HEALTH_KEY == "model_serving:health"

    @pytest.mark.asyncio
    async def test_get_prediction_cache_uses_correct_key(self):
        """get_prediction_cache calls get_cache with prediction:{symbol}."""
        from backend.core.redis import get_prediction_cache
        key_used = None
        async def capture_get(key):
            nonlocal key_used
            key_used = key
            return None
        with patch("backend.core.redis.get_cache", side_effect=capture_get):
            await get_prediction_cache("BTCUSD")
        assert key_used == "prediction:BTCUSD"
