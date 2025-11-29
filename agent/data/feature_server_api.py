"""
HTTP API wrapper for the MCP Feature Server.

Provides a lightweight aiohttp service that exposes the existing MCP
feature computation endpoints so the backend can call them via REST.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from aiohttp import web
import structlog

from agent.data.feature_server import (
    MCPFeatureServer,
    MCPFeatureRequest,
    MCPFeatureResponse,
)

logger = structlog.get_logger()


class FeatureServerAPI:
    """Expose MCP Feature Server over HTTP."""

    def __init__(self, feature_server: MCPFeatureServer, host: str, port: int):
        """Initialize HTTP bridge.

        Args:
            feature_server: Underlying MCP feature server
            host: Host interface to bind
            port: Port to listen on
        """
        self.feature_server = feature_server
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.add_routes(
            [
                web.post("/features", self._handle_features),
                web.get("/health", self._handle_health),
            ]
        )
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self) -> None:
        """Start HTTP server if not already running."""
        if self._runner is not None:
            return

        try:
            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self.host, self.port)
            await self._site.start()
            logger.info(
                "feature_server_api_started",
                host=self.host,
                port=self.port,
            )
        except Exception as exc:
            logger.error(
                "feature_server_api_start_failed",
                host=self.host,
                port=self.port,
                error=str(exc),
                exc_info=True,
            )
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        """Stop HTTP server."""
        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        logger.info("feature_server_api_stopped")

    async def _handle_features(self, request: web.Request) -> web.Response:
        """Handle POST /features requests."""
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON payload"}, status=400
            )

        try:
            feature_request = self._build_feature_request(payload)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        response: MCPFeatureResponse = await self.feature_server.get_features(
            feature_request
        )
        return web.json_response(response.model_dump(mode="json"))

    async def _handle_health(self, _: web.Request) -> web.Response:
        """Handle GET /health requests."""
        try:
            status = await self.feature_server.get_health_status()
            status.setdefault("service", "feature_server_api")
            status.setdefault("status", "up")
            return web.json_response(status)
        except Exception as exc:
            logger.error(
                "feature_server_api_health_failed",
                error=str(exc),
                exc_info=True,
            )
            return web.json_response(
                {"status": "down", "error": str(exc)}, status=503
            )

    @staticmethod
    def _build_feature_request(payload: Dict[str, Any]) -> MCPFeatureRequest:
        """Validate and normalize external request payload."""
        feature_names = payload.get("feature_names")
        symbol = payload.get("symbol")

        if not feature_names or not isinstance(feature_names, list):
            raise ValueError("feature_names must be a non-empty list")
        if not symbol:
            raise ValueError("symbol is required")

        # Let Pydantic handle timestamp and enum coercion.
        return MCPFeatureRequest.model_validate(
            {
                "feature_names": feature_names,
                "symbol": symbol,
                "timestamp": payload.get("timestamp"),
                "version": payload.get("version", "latest"),
                "require_quality": payload.get("require_quality", "medium"),
            }
        )

