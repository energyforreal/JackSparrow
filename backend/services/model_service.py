"""
Model serving client for direct inference.

Calls the model-serving endpoint (agent feature server or dedicated service)
for predictions. Used as primary path with agent command as fallback.
"""

import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import structlog

import httpx

from backend.core.config import settings

logger = structlog.get_logger()

# Base URL for model serving: explicit MODEL_SERVING_URL or FEATURE_SERVER_URL
def _model_serving_base() -> str:
    base = (settings.model_serving_url or "").strip()
    if not base:
        base = settings.feature_server_url or "http://localhost:8002"
    return base.rstrip("/")


def _float_to_signal(value: float) -> str:
    """Map continuous prediction in [-1, 1] to discrete signal."""
    if value is None:
        return "HOLD"
    if abs(value) < 0.2:
        return "HOLD"
    if value > 0.6:
        return "STRONG_BUY"
    if value > 0.2:
        return "BUY"
    if value < -0.6:
        return "STRONG_SELL"
    return "SELL"


class ModelService:
    """Client for model-serving HTTP API (predict, health)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 25.0,
        retries: int = 1,
    ):
        self.base_url = base_url or _model_serving_base()
        self.timeout = timeout
        self.retries = max(0, retries)

    async def get_prediction(
        self,
        symbol: str = "BTCUSD",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Request prediction from model-serving endpoint.

        Returns agent-shaped dict: {"success": True, "data": {...}} with
        signal, confidence, reasoning_chain, model_predictions, timestamp,
        inference_latency_ms, source="model_service". Returns None on failure.
        """
        url = f"{self.base_url}/api/v1/models/predict"
        payload = {
            "symbol": symbol,
            "model_names": None,
            "timestamp": None,
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                start = time.perf_counter()
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload)
                latency_ms = (time.perf_counter() - start) * 1000
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # If the target is a feature-only bridge (no /api/v1/models),
                    # treat 404 as \"no direct model endpoint\" and rely on agent fallback.
                    if e.response is not None and e.response.status_code == 404:
                        last_error = e
                        logger.info(
                            "model_service_predict_not_supported",
                            url=url,
                            symbol=symbol,
                            status=e.response.status_code,
                            attempt=attempt + 1,
                            message="Model endpoint not exposed on model_service URL; falling back to agent path",
                        )
                        return None
                    raise
                data = resp.json()
                return self._normalize_prediction_response(
                    data, symbol=symbol, inference_latency_ms=latency_ms
                )
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "model_service_predict_timeout",
                    url=url,
                    symbol=symbol,
                    attempt=attempt + 1,
                    error=str(e),
                )
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    "model_service_predict_http_error",
                    url=url,
                    symbol=symbol,
                    status=e.response.status_code,
                    attempt=attempt + 1,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "model_service_predict_error",
                    url=url,
                    symbol=symbol,
                    attempt=attempt + 1,
                    error=str(e),
                )
        if last_error:
            logger.debug(
                "model_service_predict_failed",
                url=url,
                symbol=symbol,
                error=str(last_error),
            )
        return None

    def _normalize_prediction_response(
        self,
        data: Dict[str, Any],
        symbol: str,
        inference_latency_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Map model-serving response to agent-style decision data."""
        predictions = data.get("predictions") or {}
        consensus_signal = float(data.get("consensus_signal", 0.0))
        confidence = float(data.get("confidence", 0.0))
        ts = data.get("timestamp")
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
        computation_ms = float(data.get("computation_time_ms", 0.0))

        model_predictions = []
        for model_name, pred_obj in predictions.items():
            if isinstance(pred_obj, dict):
                pred_val = pred_obj.get("prediction", 0.0)
                conf = pred_obj.get("confidence", 0.0)
            else:
                pred_val = 0.0
                conf = 0.0
            model_predictions.append({
                "model_name": model_name,
                "prediction": float(pred_val),
                "confidence": float(conf),
                "reasoning": f"Model {model_name} prediction {pred_val:.3f} (confidence {conf:.2f}).",
            })

        signal = _float_to_signal(consensus_signal)
        conclusion = (
            f"Model-service consensus: {signal} (raw {consensus_signal:.3f}), "
            f"confidence {confidence:.2f}, latency {inference_latency_ms:.0f}ms."
        )
        reasoning_chain = {
            "chain_id": "model_service",
            "timestamp": timestamp.isoformat(),
            "steps": [],
            "conclusion": conclusion,
            "final_confidence": confidence,
        }

        decision_data = {
            "signal": signal,
            "confidence": confidence,
            "reasoning_chain": reasoning_chain,
            "model_predictions": model_predictions,
            "timestamp": timestamp.isoformat(),
            "market_context": {"symbol": symbol},
            "inference_latency_ms": inference_latency_ms,
            "computation_time_ms": computation_ms,
            "source": "model_service",
        }
        return {"success": True, "data": decision_data}

    async def get_health(self) -> Dict[str, Any]:
        """
        Check model-serving health (list models or predict readiness).

        Returns dict with status ("up" | "down"), latency_ms, error, details.
        """
        url = f"{self.base_url}/api/v1/models"
        try:
            start = time.perf_counter()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
            latency_ms = (time.perf_counter() - start) * 1000
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models") or []
            return {
                "status": "up",
                "latency_ms": round(latency_ms, 2),
                "details": {
                    "model_count": len(models),
                    "models": [m.get("name") for m in models if isinstance(m, dict)],
                    "mode": "direct_model_endpoint",
                },
            }
        except httpx.TimeoutException as e:
            return {
                "status": "down",
                "error": "timeout",
                "details": {"message": str(e)},
            }
        except httpx.HTTPStatusError as e:
            # In Docker, FEATURE_SERVER_URL commonly points to the feature bridge
            # (`agent/data/feature_server_api.py`) which exposes `/health` and
            # `/features` but not `/api/v1/models`. Treat that as available bridge
            # instead of hard-down for system-health purposes.
            if e.response.status_code == 404:
                bridge_url = f"{self.base_url}/health"
                try:
                    start = time.perf_counter()
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        bridge_resp = await client.get(bridge_url)
                    latency_ms = (time.perf_counter() - start) * 1000
                    bridge_resp.raise_for_status()
                    return {
                        "status": "up",
                        "latency_ms": round(latency_ms, 2),
                        "details": {
                            "mode": "feature_bridge_health",
                            "note": (
                                "Direct model endpoint not exposed on this URL; "
                                "feature bridge is healthy and agent fallback remains active."
                            ),
                        },
                    }
                except Exception as bridge_error:
                    return {
                        "status": "degraded",
                        "error": "http_404",
                        "latency_ms": None,
                        "details": {
                            "message": str(e),
                            "bridge_health_error": str(bridge_error),
                            "note": (
                                "Direct model endpoint is unavailable on this URL; "
                                "backend will continue with agent fallback."
                            ),
                        },
                    }
            return {
                "status": "down",
                "error": f"http_{e.response.status_code}",
                "latency_ms": None,
                "details": {"message": str(e)},
            }
        except Exception as e:
            return {
                "status": "down",
                "error": str(e),
                "details": {"message": str(e)},
            }


# Singleton used by routes and health
model_service = ModelService()
