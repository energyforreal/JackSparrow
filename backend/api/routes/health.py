"""
Health check endpoints.

Provides comprehensive health status for all system components.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, status
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import time
from collections import defaultdict
from typing import Dict, Tuple

from backend.core.database import get_db
from backend.core.redis import redis_health_check
from backend.api.models.responses import HealthResponse, HealthServiceStatus
from backend.services.agent_service import agent_service

# Health check endpoints are intentionally public (no authentication required)
# This allows monitoring systems and load balancers to check service health
router = APIRouter()

# Lightweight in-memory rate limiter for health endpoint
# Allows 100 requests per minute per IP (more lenient than regular API)
_health_rate_limit: Dict[str, list] = defaultdict(list)
_health_rate_limit_requests = 100
_health_rate_limit_window = 60  # 60 seconds


async def check_database_health(db: AsyncSession) -> HealthServiceStatus:
    """Check database health independently."""
    try:
        start_time = time.time()
        await db.execute(text("SELECT 1"))
        await db.commit()
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


async def check_agent_health() -> HealthServiceStatus:
    """Check agent service health independently."""
    try:
        agent_status = await agent_service.get_agent_status()
        return HealthServiceStatus(
            status="up" if agent_status.get("available", False) else "down",
            latency_ms=agent_status.get("latency_ms"),
            details=agent_status
        )
    except Exception as e:
        return HealthServiceStatus(
            status="down",
            error=str(e),
            details={"error": "Agent service check failed"}
        )


async def check_feature_server_health() -> HealthServiceStatus:
    """Check feature server health independently (not via agent)."""
    try:
        # Try to check feature server directly if possible
        # For now, check via agent but handle failures gracefully
        agent_status = await agent_service.get_agent_status()
        feature_server_status = agent_status.get("feature_server", {})
        
        if feature_server_status:
            return HealthServiceStatus(
                status=feature_server_status.get("status", "unknown"),
                latency_ms=feature_server_status.get("latency_ms"),
                details=feature_server_status
            )
        else:
            # Agent is available but feature server status not provided
            return HealthServiceStatus(
                status="unknown",
                error="Feature server status not available",
                details={"note": "Agent available but feature server status unknown"}
            )
    except Exception as e:
        # Agent service unavailable - report feature server as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check feature server: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify feature server"}
        )


async def check_model_nodes_health() -> HealthServiceStatus:
    """Check model nodes health independently (not via agent)."""
    try:
        agent_status = await agent_service.get_agent_status()
        model_nodes_status = agent_status.get("model_nodes", {})
        
        if model_nodes_status:
            healthy_count = model_nodes_status.get("healthy_models", 0)
            total_count = model_nodes_status.get("total_models", 0)
            status_from_agent = model_nodes_status.get("status", "unknown")
            
            # If no models are loaded, return "unknown" (not "down") since this is acceptable in paper trading mode
            if total_count == 0:
                return HealthServiceStatus(
                    status="unknown",
                    details={
                        **model_nodes_status,
                        "note": "No models loaded - agent can function in paper trading mode without ML models"
                    }
                )
            
            # Use status from agent if available, otherwise determine from healthy count
            if status_from_agent != "unknown":
                return HealthServiceStatus(
                    status=status_from_agent,
                    details=model_nodes_status
                )
            else:
                return HealthServiceStatus(
                    status="up" if healthy_count > 0 else "down",
                    details=model_nodes_status
                )
        else:
            return HealthServiceStatus(
                status="unknown",
                error="Model nodes status not available",
                details={"note": "Agent available but model nodes status unknown"}
            )
    except Exception as e:
        # Agent service unavailable - report model nodes as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check model nodes: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify model nodes"}
        )


async def check_delta_exchange_health() -> HealthServiceStatus:
    """Check Delta Exchange API health independently (not via agent)."""
    try:
        agent_status = await agent_service.get_agent_status()
        delta_status = agent_status.get("delta_exchange", {})
        
        if delta_status:
            return HealthServiceStatus(
                status=delta_status.get("status", "unknown"),
                latency_ms=delta_status.get("latency_ms"),
                details=delta_status
            )
        else:
            return HealthServiceStatus(
                status="unknown",
                error="Delta Exchange status not available",
                details={"note": "Agent available but Delta Exchange status unknown"}
            )
    except Exception as e:
        # Agent service unavailable - report Delta Exchange as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check Delta Exchange: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify Delta Exchange"}
        )


async def check_reasoning_engine_health() -> HealthServiceStatus:
    """Check reasoning engine health independently (not via agent)."""
    try:
        agent_status = await agent_service.get_agent_status()
        reasoning_status = agent_status.get("reasoning_engine", {})
        
        if reasoning_status:
            return HealthServiceStatus(
                status=reasoning_status.get("status", "unknown"),
                details=reasoning_status
            )
        else:
            return HealthServiceStatus(
                status="unknown",
                error="Reasoning engine status not available",
                details={"note": "Agent available but reasoning engine status unknown"}
            )
    except Exception as e:
        # Agent service unavailable - report reasoning engine as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check reasoning engine: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify reasoning engine"}
        )


def _check_health_rate_limit(client_ip: str) -> bool:
    """Check if health endpoint request is within rate limit.
    
    Args:
        client_ip: Client IP address
        
    Returns:
        True if within limit, False if rate limited
    """
    current_time = time.time()
    
    # Clean old entries (older than window)
    _health_rate_limit[client_ip] = [
        req_time for req_time in _health_rate_limit[client_ip]
        if current_time - req_time < _health_rate_limit_window
    ]
    
    # Check if limit exceeded
    if len(_health_rate_limit[client_ip]) >= _health_rate_limit_requests:
        return False
    
    # Record this request
    _health_rate_limit[client_ip].append(current_time)
    return True


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Comprehensive health check endpoint.
    
    Checks status of all system components:
    - Database connection
    - Redis connection
    - Agent service
    - Delta Exchange API (via agent)
    - Feature server
    - Model nodes
    
    Rate limited to 100 requests per minute per IP to prevent abuse.
    """
    # Apply lightweight rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not _check_health_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Health check rate limit exceeded. Maximum 100 requests per minute per IP.",
            headers={"Retry-After": str(_health_rate_limit_window)},
        )
    
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
    
    # Check agent (independent check)
    agent_health = await check_agent_health()
    agent_weight = 0.15  # 15% weight
    if agent_health.status == "up":
        health_scores.append(agent_weight)
        agent_state = agent_health.details.get("state") if agent_health.details else None
    else:
        degradation_reasons.append("Agent service is down")
        health_scores.append(0.0)
        agent_state = None
    
    # Check feature server (independent check, not via agent)
    feature_health = await check_feature_server_health()
    feature_weight = 0.20  # 20% weight
    if feature_health.status == "up":
        health_scores.append(feature_weight)
    elif feature_health.status == "unknown":
        # Don't add to degradation reasons if status is unknown (agent unavailable)
        health_scores.append(0.0)
    else:
        degradation_reasons.append("Feature server is down")
        health_scores.append(0.0)
    
    # Check model nodes (independent check, not via agent)
    model_health = await check_model_nodes_health()
    model_weight = 0.25  # 25% weight
    if model_health.status == "up":
        # Scale weight based on healthy models count if available
        if model_health.details:
            healthy_count = model_health.details.get("healthy_models", 0)
            total_count = model_health.details.get("total_models", 1)
            if healthy_count < 3 and total_count > 0:
                degradation_reasons.append(f"Only {healthy_count}/{total_count} models are healthy")
            health_scores.append(model_weight * (healthy_count / max(total_count, 1)))
        else:
            health_scores.append(model_weight)
    elif model_health.status == "unknown":
        # Don't add to degradation reasons if status is unknown (agent unavailable)
        health_scores.append(0.0)
    else:
        degradation_reasons.append("No model nodes are healthy")
        health_scores.append(0.0)
    
    # Check Delta Exchange (independent check, not via agent)
    delta_health = await check_delta_exchange_health()
    delta_weight = 0.15  # 15% weight
    if delta_health.status == "up":
        health_scores.append(delta_weight)
    elif delta_health.status == "unknown":
        # Don't add to degradation reasons if status is unknown (agent unavailable)
        health_scores.append(0.0)
    else:
        degradation_reasons.append("Delta Exchange API is down")
        health_scores.append(0.0)
    
    # Check reasoning engine (independent check, not via agent)
    reasoning_health = await check_reasoning_engine_health()
    reasoning_weight = 0.15  # 15% weight
    if reasoning_health.status == "up":
        health_scores.append(reasoning_weight)
    elif reasoning_health.status == "unknown":
        # Don't add to degradation reasons if status is unknown (agent unavailable)
        health_scores.append(0.0)
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

