"""
Health check endpoints.

Provides comprehensive health status for all system components.
"""

from fastapi import APIRouter, Depends
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
import time

from backend.core.database import get_db
from backend.core.redis import redis_health_check
from backend.api.models.responses import HealthResponse, HealthServiceStatus
from backend.services.agent_service import agent_service

router = APIRouter()


async def check_database_health(db: Session) -> HealthServiceStatus:
    """Check database health."""
    try:
        start_time = time.time()
        db.execute(text("SELECT 1"))
        db.commit()
        latency_ms = (time.time() - start_time) * 1000
        
        return HealthServiceStatus(
            status="up",
            latency_ms=round(latency_ms, 2)
        )
    except Exception as e:
        return HealthServiceStatus(
            status="down",
            error=str(e)
        )


@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """
    Comprehensive health check endpoint.
    
    Checks status of all system components:
    - Database connection
    - Redis connection
    - Agent service
    - Delta Exchange API (via agent)
    - Feature server
    - Model nodes
    """
    
    degradation_reasons = []
    health_scores = []
    
    # Check database
    db_health = await check_database_health(db)
    if db_health.status == "up":
        health_scores.append(0.05)  # 5% weight
    else:
        degradation_reasons.append("Database is down")
        health_scores.append(0.0)
    
    # Check Redis
    redis_health = await redis_health_check()
    redis_status = HealthServiceStatus(**redis_health)
    if redis_status.status == "up":
        health_scores.append(0.05)  # 5% weight
    else:
        degradation_reasons.append("Redis is down")
        health_scores.append(0.0)
    
    # Check agent
    agent_status = await agent_service.get_agent_status()
    agent_health = HealthServiceStatus(
        status="up" if agent_status.get("available", False) else "down",
        latency_ms=agent_status.get("latency_ms"),
        details=agent_status
    )
    
    agent_weight = 0.15  # 15% weight
    if agent_health.status == "up":
        health_scores.append(agent_weight)
        agent_state = agent_status.get("state", "UNKNOWN")
    else:
        degradation_reasons.append("Agent service is down")
        health_scores.append(0.0)
        agent_state = None
    
    # Check feature server (via agent)
    feature_server_status = agent_status.get("feature_server", {})
    feature_health = HealthServiceStatus(
        status=feature_server_status.get("status", "unknown"),
        latency_ms=feature_server_status.get("latency_ms"),
        details=feature_server_status
    )
    
    feature_weight = 0.20  # 20% weight
    if feature_health.status == "up":
        health_scores.append(feature_weight)
    else:
        degradation_reasons.append("Feature server is down")
        health_scores.append(0.0)
    
    # Check model nodes (via agent)
    model_nodes_status = agent_status.get("model_nodes", {})
    model_health = HealthServiceStatus(
        status="up" if model_nodes_status.get("healthy_models", 0) > 0 else "down",
        details=model_nodes_status
    )
    
    model_weight = 0.25  # 25% weight
    if model_health.status == "up":
        # Scale weight based on healthy models count
        healthy_count = model_nodes_status.get("healthy_models", 0)
        total_count = model_nodes_status.get("total_models", 1)
        if healthy_count < 3:
            degradation_reasons.append(f"Only {healthy_count}/{total_count} models are healthy")
        health_scores.append(model_weight * (healthy_count / max(total_count, 1)))
    else:
        degradation_reasons.append("No model nodes are healthy")
        health_scores.append(0.0)
    
    # Check Delta Exchange (via agent)
    delta_status = agent_status.get("delta_exchange", {})
    delta_health = HealthServiceStatus(
        status=delta_status.get("status", "unknown"),
        latency_ms=delta_status.get("latency_ms"),
        details=delta_status
    )
    
    delta_weight = 0.15  # 15% weight
    if delta_health.status == "up":
        health_scores.append(delta_weight)
    else:
        degradation_reasons.append("Delta Exchange API is down")
        health_scores.append(0.0)
    
    # Check reasoning engine (via agent)
    reasoning_status = agent_status.get("reasoning_engine", {})
    reasoning_health = HealthServiceStatus(
        status=reasoning_status.get("status", "unknown"),
        details=reasoning_status
    )
    
    reasoning_weight = 0.15  # 15% weight
    if reasoning_health.status == "up":
        health_scores.append(reasoning_weight)
    else:
        degradation_reasons.append("Reasoning engine is down")
        health_scores.append(0.0)
    
    # Calculate overall health score
    health_score = sum(health_scores)
    
    # Determine status
    if health_score >= 0.9:
        status = "healthy"
    elif health_score >= 0.6:
        status = "degraded"
    else:
        status = "unhealthy"
    
    return HealthResponse(
        status=status,
        health_score=round(health_score, 3),
        services={
            "database": db_health,
            "redis": redis_status,
            "agent": agent_health,
            "feature_server": feature_health,
            "model_nodes": model_health,
            "delta_exchange": delta_health,
            "reasoning_engine": reasoning_health
        },
        agent_state=agent_state,
        degradation_reasons=degradation_reasons,
        timestamp=datetime.utcnow()
    )

