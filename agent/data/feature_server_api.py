"""
HTTP API wrapper for the MCP Feature Server.

Provides a lightweight aiohttp service that exposes the existing MCP
feature computation endpoints so the backend can call them via REST.
"""

from __future__ import annotations

import socket
import asyncio
from typing import Any, Dict, Optional
from aiohttp import web
import structlog

from agent.data.feature_server import (
    MCPFeatureServer,
    MCPFeatureRequest,
    MCPFeatureResponse,
)

logger = structlog.get_logger()


def _is_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding.
    
    Args:
        host: Host address to check
        port: Port number to check
        
    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            result = s.bind((host, port))
            return True
    except OSError:
        return False


def _find_free_port(start_port: int, max_attempts: int = 10) -> Optional[int]:
    """Find a free port starting from start_port.
    
    Args:
        start_port: Starting port number
        max_attempts: Maximum number of ports to try
        
    Returns:
        First available port number, or None if none found
    """
    for port in range(start_port, start_port + max_attempts):
        if _is_port_available("0.0.0.0", port):
            return port
    return None


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
        self.original_port = port
        self.port = port
        self._app = web.Application()
        self._app.add_routes(
            [
                web.post("/features", self._handle_features),
                web.get("/health", self._handle_health),
                # Expose model and feature discovery endpoints for backend/UX
                web.get("/api/v1/models", self._handle_models),
                web.get("/api/v1/features", self._handle_feature_list),
            ]
        )
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def start(self, max_retries: int = 3, retry_delay: float = 1.0) -> None:
        """Start HTTP server if not already running.
        
        Args:
            max_retries: Maximum number of retry attempts with port conflict resolution
            retry_delay: Initial delay between retries (exponential backoff)
            
        Raises:
            OSError: If port binding fails after all retries and conflict resolution attempts
        """
        if self._runner is not None:
            return

        last_exception: Optional[Exception] = None
        
        for attempt in range(max_retries):
            try:
                # Check if port is available before attempting to bind
                if not _is_port_available(self.host, self.port):
                    if attempt < max_retries - 1:
                        # Try to find an alternative port
                        alternative_port = _find_free_port(
                            self.port + 1, 
                            max_attempts=20
                        )
                        if alternative_port:
                            logger.warning(
                                "feature_server_api_port_conflict",
                                original_port=self.port,
                                alternative_port=alternative_port,
                                attempt=attempt + 1,
                                message=f"Port {self.port} is in use, trying alternative port {alternative_port}"
                            )
                            self.port = alternative_port
                        else:
                            # Wait and retry with exponential backoff
                            wait_time = retry_delay * (2 ** attempt)
                            logger.warning(
                                "feature_server_api_port_busy",
                                port=self.port,
                                attempt=attempt + 1,
                                wait_time=wait_time,
                                message=f"Port {self.port} is busy, waiting {wait_time}s before retry"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                    else:
                        # Last attempt - provide helpful error message
                        raise OSError(
                            f"Port {self.port} is not available. "
                            f"This usually means another process is using the port. "
                            f"Solutions:\n"
                            f"1. Stop the process using port {self.port}:\n"
                            f"   Windows: Get-NetTCPConnection -LocalPort {self.port} | "
                            f"Select-Object -ExpandProperty OwningProcess | "
                            f"ForEach-Object {{ Stop-Process -Id $_ -Force }}\n"
                            f"   Linux/Mac: lsof -ti:{self.port} | xargs kill -9\n"
                            f"2. Set FEATURE_SERVER_PORT environment variable to a different port\n"
                            f"3. Wait for the port to be released"
                        )
                
                # Attempt to start the server
                self._runner = web.AppRunner(self._app)
                await self._runner.setup()
                self._site = web.TCPSite(self._runner, self.host, self.port)
                await self._site.start()
                
                if self.port != self.original_port:
                    logger.info(
                        "feature_server_api_started_alternative_port",
                        host=self.host,
                        original_port=self.original_port,
                        actual_port=self.port,
                        message=f"Started on alternative port {self.port} (requested {self.original_port})"
                    )
                else:
                    logger.info(
                        "feature_server_api_started",
                        host=self.host,
                        port=self.port,
                    )
                return
                
            except OSError as exc:
                last_exception = exc
                error_code = getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)
                
                # Check if it's a port conflict error
                is_port_conflict = (
                    error_code == 10048 or  # Windows: WSAEADDRINUSE
                    error_code == 98 or     # Linux: EADDRINUSE
                    "Address already in use" in str(exc) or
                    "only one usage of each socket address" in str(exc)
                )
                
                if is_port_conflict and attempt < max_retries - 1:
                    # Try to find an alternative port
                    alternative_port = _find_free_port(
                        self.port + 1,
                        max_attempts=20
                    )
                    if alternative_port:
                        logger.warning(
                            "feature_server_api_port_conflict_retry",
                            original_port=self.port,
                            alternative_port=alternative_port,
                            attempt=attempt + 1,
                            error=str(exc),
                            message=f"Port conflict detected, switching to port {alternative_port}"
                        )
                        self.port = alternative_port
                        continue
                    else:
                        # Wait and retry with exponential backoff
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(
                            "feature_server_api_port_conflict_wait",
                            port=self.port,
                            attempt=attempt + 1,
                            wait_time=wait_time,
                            error=str(exc),
                            message=f"Port conflict, waiting {wait_time}s before retry"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                else:
                    # Not a port conflict or last attempt
                    logger.error(
                        "feature_server_api_start_failed",
                        host=self.host,
                        port=self.port,
                        attempt=attempt + 1,
                        error=str(exc),
                        error_code=error_code,
                        exc_info=True,
                    )
                    await self.shutdown()
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(retry_delay * (2 ** attempt))
                    
            except Exception as exc:
                last_exception = exc
                logger.error(
                    "feature_server_api_start_failed",
                    host=self.host,
                    port=self.port,
                    attempt=attempt + 1,
                    error=str(exc),
                    exc_info=True,
                )
                await self.shutdown()
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(retry_delay * (2 ** attempt))
        
        # If we get here, all retries failed
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Failed to start feature server API after {max_retries} attempts")

    async def shutdown(self) -> None:
        """Stop HTTP server."""
        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        logger.info("feature_server_api_stopped")

    def _resolve_feature_server(self) -> Optional[MCPFeatureServer]:
        """Resolve feature server instance with fallback to global orchestrator state."""
        if self.feature_server is not None:
            return self.feature_server

        try:
            # Late import avoids circular imports at module load time.
            from agent.core.mcp_orchestrator import mcp_orchestrator

            if mcp_orchestrator and getattr(mcp_orchestrator, "feature_server", None) is not None:
                self.feature_server = mcp_orchestrator.feature_server
        except Exception:
            # Keep existing None and let callers return a graceful response.
            pass

        return self.feature_server

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

        feature_server = self._resolve_feature_server()
        if feature_server is None:
            return web.json_response(
                {
                    "status": "degraded",
                    "error": "Feature server is not initialized yet",
                    "message": "Retry shortly; MCP orchestrator may still be starting",
                },
                status=503,
            )

        response: MCPFeatureResponse = await feature_server.get_features(
            feature_request
        )
        return web.json_response(response.model_dump(mode="json"))

    async def _handle_health(self, _: web.Request) -> web.Response:
        """Handle GET /health requests."""
        try:
            feature_server = self._resolve_feature_server()
            if feature_server is None:
                # Return a non-5xx degraded status so backend health can use fallback
                # paths instead of marking model-serving hard down.
                return web.json_response(
                    {
                        "status": "degraded",
                        "service": "feature_server_api",
                        "note": "Feature server not bound yet; orchestrator still initializing",
                    },
                    status=200,
                )

            status = await feature_server.get_health_status()
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

    async def _handle_models(self, _: web.Request) -> web.Response:
        """Handle GET /api/v1/models requests.

        Returns a lightweight list of models registered in the MCP model registry.
        Shape matches what backend ModelService expects:
            {"models": [{"name": ..., "type": ..., "status": "loaded"}, ...], "count": N}
        """
        try:
            # Late import to avoid circulars; mirrors pattern used elsewhere.
            from agent.core.mcp_orchestrator import mcp_orchestrator
        except Exception:
            mcp_orchestrator = None  # type: ignore[assignment]

        orchestrator = mcp_orchestrator  # type: ignore[name-defined]

        if orchestrator is None or getattr(orchestrator, "model_registry", None) is None:
            return web.json_response(
                {"error": "Model registry not available"}, status=503
            )

        try:
            models_info = []
            for name, model in orchestrator.model_registry.models.items():
                models_info.append(
                    {
                        "name": name,
                        "type": getattr(model, "model_type", "unknown"),
                        "status": "loaded",
                    }
                )

            return web.json_response(
                {"models": models_info, "count": len(models_info)}
            )
        except Exception as exc:
            logger.error(
                "feature_server_api_list_models_failed",
                error=str(exc),
                exc_info=True,
            )
            return web.json_response(
                {"error": f"Failed to list models: {exc}"}, status=500
            )

    async def _handle_feature_list(self, _: web.Request) -> web.Response:
        """Handle GET /api/v1/features requests.

        Returns a simple list of features exposed by the MCP Feature Server.
        Shape is similar to the FastAPI feature server implementation.
        """
        feature_server = self._resolve_feature_server()
        if feature_server is None:
            return web.json_response(
                {"error": "Feature server not available"}, status=503
            )

        try:
            features_info = []
            # feature_registry is a mapping name -> version in the orchestrator-backed server
            for name, version in getattr(
                feature_server, "feature_registry", {}
            ).items():
                features_info.append(
                    {
                        "name": name,
                        "version": version,
                        "status": "available",
                    }
                )

            return web.json_response(
                {"features": features_info, "count": len(features_info)}
            )
        except Exception as exc:
            logger.error(
                "feature_server_api_list_features_failed",
                error=str(exc),
                exc_info=True,
            )
            return web.json_response(
                {"error": f"Failed to list features: {exc}"}, status=500
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

