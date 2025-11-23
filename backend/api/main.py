"""
FastAPI application entry point.

Main application initialization with routes, middleware, and lifecycle events.
"""

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import os
import sys
import time
import uuid
import structlog
from sqlalchemy import text

from backend.core.config import settings

logger = structlog.get_logger()
from backend.core.database import engine, Base
from backend.core.redis import get_redis, close_redis
from backend.api.routes import health, trading, portfolio, market, admin, system
from backend.api.websocket.manager import websocket_manager


def _configure_utf8_stdio() -> None:
    """Ensure console output uses UTF-8 (fixes Windows encoding errors)."""
    if os.name != "nt":
        return
    
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


_configure_utf8_stdio()


async def _verify_database_connection() -> None:
    """Ensure database engine can establish a connection."""
    async with engine.begin() as connection:
        await connection.execute(text("SELECT 1"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("backend_starting", service="backend")
    
    # Initialize database
    try:
        await _verify_database_connection()
        logger.info("backend_database_connected", service="backend")
    except Exception as e:
        logger.error(
            "backend_database_connection_failed",
            service="backend",
            error=str(e),
            exc_info=True
        )
    
    # Initialize Redis
    try:
        redis_client = await get_redis()
        if redis_client is not None:
            await redis_client.ping()
            logger.info("backend_redis_connected", service="backend")
        else:
            logger.warning(
                "backend_redis_unavailable",
                service="backend",
                message="Redis is optional and unavailable"
            )
    except Exception as e:
        logger.error(
            "backend_redis_connection_failed",
            service="backend",
            error=str(e),
            exc_info=True
        )
    
    # Initialize WebSocket manager
    try:
        await websocket_manager.initialize()
        logger.info("backend_websocket_manager_initialized", service="backend")
    except Exception as e:
        logger.warning(
            "backend_websocket_manager_init_warning",
            service="backend",
            error=str(e),
            exc_info=True
        )
    
    logger.info("backend_started_successfully", service="backend")
    
    yield
    
    # Shutdown
    logger.info("backend_shutting_down", service="backend")
    try:
        await close_redis()
        await websocket_manager.cleanup()
        logger.info("backend_shut_down", service="backend")
    except Exception as e:
        logger.error(
            "backend_shutdown_error",
            service="backend",
            error=str(e),
            exc_info=True
        )


# Create FastAPI app
app = FastAPI(
    title="JackSparrow Trading Agent API",
    description="AI-Powered Trading Agent for Delta Exchange India Paper Trading",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)


# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add request ID to request and response."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = str(process_time)
    
    return response


# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(trading.router, prefix="/api/v1", tags=["trading"])
app.include_router(portfolio.router, prefix="/api/v1", tags=["portfolio"])
app.include_router(market.router, prefix="/api/v1", tags=["market"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(system.router, prefix="/api/v1", tags=["system"])


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket_manager.connect(websocket)
    try:
        await websocket_manager.handle_client(websocket)
    except Exception as e:
        logger.error(
            "websocket_endpoint_error",
            error=str(e),
            exc_info=True
        )
    finally:
        await websocket_manager.disconnect(websocket)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "JackSparrow Trading Agent API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    # Log the exception with full context
    logger.error(
        "unhandled_exception",
        service="backend",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred",
                "request_id": request_id,
                "timestamp": time.time()
            }
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.api.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.backend_reload
    )

