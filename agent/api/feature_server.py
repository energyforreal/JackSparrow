"""
Agent Feature Server API.

HTTP API server for the MCP Feature Server, exposing feature computation
endpoints for the backend to query.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import structlog

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agent.data.feature_server import MCPFeatureServer, MCPFeatureRequest, MCPFeatureResponse
from agent.models.mcp_model_registry import MCPModelRegistry, MCPModelRequest, MCPModelResponse
from agent.core.reasoning_engine import MCPReasoningEngine
from agent.core.mcp_orchestrator import MCPOrchestrator
from agent.core.redis_config import get_redis, close_redis

logger = structlog.get_logger()

# Global orchestrator instance - will be set by intelligent_agent.py
orchestrator: Optional[MCPOrchestrator] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    services: Dict[str, Any] = Field(default_factory=dict)


class FeatureComputeRequest(BaseModel):
    """Feature computation request."""
    symbol: str = Field(..., description="Trading symbol")
    feature_names: List[str] = Field(..., description="List of feature names to compute")
    timestamp: Optional[datetime] = Field(None, description="Specific timestamp for computation")


class FeatureComputeResponse(BaseModel):
    """Feature computation response."""
    symbol: str
    features: Dict[str, Any]
    timestamp: datetime
    computation_time_ms: float
    status: str = "success"


class ModelPredictionRequest(BaseModel):
    """Model prediction request."""
    symbol: str = Field(..., description="Trading symbol")
    model_names: Optional[List[str]] = Field(None, description="Specific models to use")
    timestamp: Optional[datetime] = Field(None, description="Timestamp for prediction")


class ModelPredictionResponse(BaseModel):
    """Model prediction response."""
    symbol: str
    predictions: Dict[str, Any]
    consensus_signal: float
    confidence: float
    timestamp: datetime
    computation_time_ms: float
    status: str = "success"


class AgentStatusResponse(BaseModel):
    """Agent status response."""
    state: str
    available: bool
    last_update: Optional[datetime]
    active_symbols: List[str] = Field(default_factory=list)
    model_count: int = 0
    health_status: str = "unknown"
    message: Optional[str] = None
    latency_ms: Optional[float] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global orchestrator

    logger.info("feature_server_starting", message="Starting MCP Feature Server")

    try:
        # Try to import and use the global orchestrator instance
        from agent.core.mcp_orchestrator import mcp_orchestrator
        orchestrator = mcp_orchestrator
        logger.info("feature_server_orchestrator_connected", message="Connected to global MCP Orchestrator")
    except Exception as e:
        logger.warning("feature_server_orchestrator_not_available", error=str(e), message="Global orchestrator not available, HTTP server will return limited functionality")
        orchestrator = None

    yield

    # Note: Don't shutdown the orchestrator here as it's managed by the main agent process
    logger.info("feature_server_shutdown", message="MCP Feature Server shut down")


# Create FastAPI app
app = FastAPI(
    title="JackSparrow Agent Feature Server",
    description="MCP Feature Server API for AI Trading Agent",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/live")
async def live_check():
    """Fast liveness probe (process listening); no dependency checks."""
    return {"status": "live"}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    logger.info("health_check_called", orchestrator_exists=orchestrator is not None)

    services_status = {}

    try:
        # Check Redis connectivity
        redis_client = await get_redis()
        if redis_client:
            pong = await redis_client.ping()
            services_status["redis"] = {"status": "up" if pong else "down"}
            await close_redis()
        else:
            services_status["redis"] = {"status": "down"}
    except Exception as e:
        logger.error("redis_health_check_error", error=str(e))
        services_status["redis"] = {"status": "error", "error": str(e)}

    # Check orchestrator status
    logger.debug("health_check_orchestrator_status",
                orchestrator_is_none=orchestrator is None,
                orchestrator_type=type(orchestrator) if orchestrator else None)

    if orchestrator is None:
        services_status["orchestrator"] = {"status": "not_available", "note": "Orchestrator not initialized"}
        services_status["feature_server"] = {"status": "limited", "note": "Running without orchestrator"}
        services_status["model_registry"] = {"status": "not_available"}
        services_status["reasoning_engine"] = {"status": "not_available"}
    else:
        try:
            if hasattr(orchestrator, '_initialized') and orchestrator._initialized:
                services_status["orchestrator"] = {"status": "up"}
                services_status["feature_server"] = {"status": "up"}
                services_status["model_registry"] = {"status": "up"}
                services_status["reasoning_engine"] = {"status": "up"}
            else:
                services_status["orchestrator"] = {"status": "down"}
                services_status["feature_server"] = {"status": "down"}
                services_status["model_registry"] = {"status": "down"}
                services_status["reasoning_engine"] = {"status": "down"}
        except Exception as e:
            logger.error("orchestrator_health_check_error", error=str(e), orchestrator_type=type(orchestrator))
            services_status["orchestrator"] = {"status": "error", "error": str(e)}
            services_status["feature_server"] = {"status": "error"}
            services_status["model_registry"] = {"status": "error"}
            services_status["reasoning_engine"] = {"status": "error"}

    overall_status = "healthy" if all(s.get("status") == "up" for s in services_status.values()) else "unhealthy"

    logger.info("health_check_complete", overall_status=overall_status, services_status=services_status)

    return HealthResponse(
        status=overall_status,
        services=services_status
    )


@app.get("/api/v1/status", response_model=AgentStatusResponse)
async def get_agent_status():
    """Get agent status."""
    if orchestrator is None:
        return AgentStatusResponse(
            state="INITIALIZING",
            available=False,
            health_status="initializing",
            message="Agent initializing"
        )
    elif not orchestrator._initialized:
        return AgentStatusResponse(
            state="UNKNOWN",
            available=False,
            health_status="unhealthy",
            message="Agent not fully initialized"
        )

    # Get basic status from orchestrator
    return AgentStatusResponse(
        state="RUNNING",
        available=True,
        last_update=datetime.utcnow(),
        active_symbols=["BTCUSD"],  # TODO: Get from orchestrator
        model_count=len(orchestrator.model_registry.models) if orchestrator.model_registry else 0,
        health_status="healthy",
        message="Agent operational"
    )


@app.post("/api/v1/features/compute", response_model=FeatureComputeResponse)
async def compute_features(request: FeatureComputeRequest, background_tasks: BackgroundTasks):
    """Compute features for a symbol."""
    if not orchestrator or not orchestrator.feature_server:
        raise HTTPException(status_code=503, detail="Feature server not available")

    start_time = datetime.utcnow()

    try:
        # Create MCP feature request
        mcp_request = MCPFeatureRequest(
            feature_names=request.feature_names,
            symbol=request.symbol,
            timestamp=request.timestamp
        )

        # Compute features
        response = await orchestrator.feature_server.compute_features(mcp_request)

        computation_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return FeatureComputeResponse(
            symbol=request.symbol,
            features={f.name: {"value": f.value, "quality": f.quality, "metadata": f.metadata}
                     for f in response.features},
            timestamp=response.timestamp,
            computation_time_ms=computation_time
        )

    except Exception as e:
        logger.error("feature_computation_error", error=str(e), symbol=request.symbol, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Feature computation failed: {str(e)}")


@app.post("/api/v1/models/predict", response_model=ModelPredictionResponse)
async def get_predictions(request: ModelPredictionRequest, background_tasks: BackgroundTasks):
    """Get model predictions for a symbol."""
    if not orchestrator or not orchestrator.model_registry:
        raise HTTPException(status_code=503, detail="Model registry not available")

    start_time = datetime.utcnow()

    try:
        # Create MCP model request
        mcp_request = MCPModelRequest(
            symbol=request.symbol,
            model_names=request.model_names,
            timestamp=request.timestamp
        )

        # Get predictions
        response = await orchestrator.model_registry.get_predictions(mcp_request)

        computation_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        return ModelPredictionResponse(
            symbol=request.symbol,
            predictions={pred.model_name: {"prediction": pred.prediction, "confidence": pred.confidence}
                        for pred in response.predictions},
            consensus_signal=response.consensus_signal,
            confidence=response.confidence,
            timestamp=response.timestamp,
            computation_time_ms=computation_time
        )

    except Exception as e:
        logger.error("model_prediction_error", error=str(e), symbol=request.symbol, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Model prediction failed: {str(e)}")


@app.get("/api/v1/models")
async def list_models():
    """List available models."""
    if not orchestrator or not orchestrator.model_registry:
        raise HTTPException(status_code=503, detail="Model registry not available")

    try:
        models_info = []
        for name, model in orchestrator.model_registry.models.items():
            models_info.append({
                "name": name,
                "type": getattr(model, 'model_type', 'unknown'),
                "status": "loaded"
            })

        return {"models": models_info, "count": len(models_info)}

    except Exception as e:
        logger.error("list_models_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")


@app.get("/api/v1/features")
async def list_features():
    """List available features."""
    if not orchestrator or not orchestrator.feature_server:
        raise HTTPException(status_code=503, detail="Feature server not available")

    try:
        features_info = []
        for name, version in orchestrator.feature_server.feature_registry.items():
            features_info.append({
                "name": name,
                "version": version,
                "status": "available"
            })

        return {"features": features_info, "count": len(features_info)}

    except Exception as e:
        logger.error("list_features_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list features: {str(e)}")


def main():
    """Main entry point for the feature server."""
    port = int(os.getenv("FEATURE_SERVER_PORT", "8001"))
    host = os.getenv("FEATURE_SERVER_HOST", "0.0.0.0")

    logger.info("starting_feature_server", host=host, port=port)

    uvicorn.run(
        "agent.api.feature_server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()