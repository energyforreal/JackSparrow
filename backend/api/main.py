"""
FastAPI application entry point.

Main application initialization with routes, middleware, and lifecycle events.
"""

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
from backend.core.logging import configure_logging, log_error_with_context, get_session_id
from backend.core.exceptions import BackendException

# Configure logging and get session ID
SESSION_ID = configure_logging()
logger = structlog.get_logger()
from backend.core.database import engine, Base
from backend.core.redis import get_redis, close_redis
from backend.api.routes import health, trading
from backend.api.websocket.unified_manager import unified_websocket_manager
from backend.services.agent_event_subscriber import agent_event_subscriber
from backend.services.health_poller import health_poller


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


async def _initialize_database_schema() -> None:
    """Create database tables/enums if they do not exist."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _reset_paper_trade_state() -> None:
    """Clear positions and trades in DB so paper trade starts fresh on each backend load."""
    from backend.core.database import AsyncSessionLocal
    from backend.core.database import Trade, Position
    from sqlalchemy import delete

    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(Trade))
            await session.execute(delete(Position))
            await session.commit()
            logger.info(
                "paper_trade_state_reset",
                service="backend",
                message="Cleared positions and trades for fresh paper trading session",
            )
        except Exception as e:
            await session.rollback()
            logger.warning(
                "paper_trade_state_reset_failed",
                service="backend",
                error=str(e),
                message="Could not reset paper trade state",
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    logger.info("backend_starting", service="backend")
    
    # Initialize database
    try:
        await _verify_database_connection()
        logger.info("backend_database_connected", service="backend")
        if settings.auto_create_db_schema:
            await _initialize_database_schema()
            logger.info(
                "backend_database_schema_created",
                service="backend",
                auto_create=True
            )
        if getattr(settings, "paper_trading_mode", True):
            try:
                await _reset_paper_trade_state()
            except Exception as reset_err:
                logger.warning(
                    "paper_trade_reset_skipped",
                    service="backend",
                    error=str(reset_err),
                    message="Paper trade state reset failed; continuing startup",
                )
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
    
    # Initialize unified WebSocket manager (single contract, legacy envelope compatible)
    try:
        await unified_websocket_manager.initialize()
        logger.info("backend_websocket_manager_initialized", service="backend")
    except Exception as e:
        logger.warning(
            "backend_websocket_manager_init_warning",
            service="backend",
            error=str(e),
            exc_info=True
        )

    # Outbound agent command WebSocket: absorb Docker bridge race after agent reports healthy.
    try:
        from backend.services.agent_service import agent_service

        await agent_service.warmup_outbound_websocket()
    except Exception as e:
        logger.warning(
            "backend_agent_outbound_ws_warmup_warning",
            service="backend",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
            message="Warmup failed; Redis fallback remains available",
        )
    
    # Initialize and start agent event subscriber (separate block so failure does not block poller)
    logger.info("backend_starting_agent_event_subscriber", service="backend")
    try:
        await agent_event_subscriber.initialize()
        await agent_event_subscriber.start()
        logger.info("backend_agent_event_subscriber_started", service="backend")
    except Exception as e:
        logger.warning(
            "backend_agent_event_subscriber_init_warning",
            service="backend",
            error=str(e),
            exc_info=True,
            message="Agent event subscriber failed; WebSocket broadcasts may be incomplete",
        )

    # Start health poller in separate block so it runs even if subscriber failed
    try:
        await health_poller.start()
        logger.info("backend_health_poller_started", service="backend")
    except Exception as e:
        logger.warning(
            "backend_health_poller_init_warning",
            service="backend",
            error=str(e),
            message="Health poller failed to start",
        )
    
    logger.info("backend_started_successfully", service="backend")
    
    yield
    
    # Shutdown
    logger.info("backend_shutting_down", service="backend")
    try:
        # Stop agent event subscriber
        try:
            await agent_event_subscriber.stop()
            logger.info("backend_agent_event_subscriber_stopped", service="backend")
        except Exception as e:
            logger.warning(
                "backend_agent_event_subscriber_stop_warning",
                service="backend",
                error=str(e)
            )
        
        await close_redis()
        await unified_websocket_manager.cleanup()
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
    allow_origins=settings.get_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

# GZip compression middleware (compress responses > 1000 bytes)
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,  # Only compress responses larger than 1KB
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


# WebSocket endpoint for frontend clients (unified manager, legacy envelope)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates to frontend clients."""
    await unified_websocket_manager.connect(websocket, is_agent=False)
    try:
        await unified_websocket_manager.handle_client(websocket)
    except Exception as e:
        logger.error(
            "websocket_endpoint_error",
            error=str(e),
            exc_info=True
        )
    finally:
        await unified_websocket_manager.disconnect(websocket, is_agent=False)


# WebSocket endpoint for agent connections
@app.websocket("/ws/agent")
async def agent_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for agent to send events directly."""
    await unified_websocket_manager.connect(websocket, is_agent=True)
    try:
        await unified_websocket_manager.handle_agent_client(websocket)
    except Exception as e:
        logger.error(
            "agent_websocket_endpoint_error",
            error=str(e),
            exc_info=True
        )
    finally:
        await unified_websocket_manager.disconnect(websocket, is_agent=True)


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
@app.exception_handler(BackendException)
async def backend_exception_handler(request: Request, exc: BackendException):
    """Handle custom backend exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    # Log the exception
    log_error_with_context(
        "backend_exception",
        error=exc,
        component="backend_exception_handler",
        request_id=request_id,
        error_code=exc.error_code,
        path=request.url.path,
        method=request.method,
    )
    
    status_code = 500
    if exc.error_code == "VALIDATION_ERROR":
        status_code = 400
    elif exc.error_code == "RATE_LIMIT_EXCEEDED":
        status_code = 429
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
                "timestamp": time.time()
            }
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    # Log the exception with full context using enhanced logging
    log_error_with_context(
        "unhandled_exception",
        error=exc,
        component="global_exception_handler",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        query_params=dict(request.query_params),
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
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

