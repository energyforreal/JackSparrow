"""
FastAPI application entry point.

Main application initialization with routes, middleware, and lifecycle events.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import uuid

from backend.core.config import settings
from backend.core.database import engine, Base
from backend.core.redis import get_redis, close_redis
from backend.api.routes import health, trading, portfolio, market, admin
from backend.api.websocket.manager import websocket_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    print("Starting backend service...")
    
    # Initialize database
    try:
        # Tables are created via Alembic migrations or setup_db.py
        # Just verify connection
        async with engine.begin() as conn:
            pass
        print("✓ Database connection verified")
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
    
    # Initialize Redis
    try:
        redis_client = await get_redis()
        await redis_client.ping()
        print("✓ Redis connection verified")
    except Exception as e:
        print(f"✗ Redis connection failed: {e}")
    
    # Initialize WebSocket manager
    await websocket_manager.initialize()
    print("✓ WebSocket manager initialized")
    
    print("✓ Backend service started successfully")
    
    yield
    
    # Shutdown
    print("Shutting down backend service...")
    await close_redis()
    await websocket_manager.cleanup()
    print("✓ Backend service shut down")


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


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket):
    """WebSocket endpoint for real-time updates."""
    await websocket_manager.connect(websocket)
    try:
        await websocket_manager.handle_client(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
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
    """Global exception handler."""
    request_id = getattr(request.state, "request_id", None)
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

