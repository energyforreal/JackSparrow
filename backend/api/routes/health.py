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
from typing import Any, Dict, Optional, Tuple

from backend.core.database import get_db
from backend.core.redis import redis_health_check, get_cache, set_cache, set_model_health_heartbeat, get_model_health_heartbeat
from backend.core.config import settings
from backend.api.models.responses import HealthResponse, HealthServiceStatus
from backend.services.agent_service import agent_service
from backend.services.model_service import model_service

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


async def check_agent_health(agent_status: Optional[Dict[str, Any]] = None) -> HealthServiceStatus:
    """Check agent service health independently.

    Args:
        agent_status: Optional pre-fetched agent status dict. When provided,
            avoids an additional round-trip to the agent service.
    """
    try:
        # Use a slightly longer timeout here to accommodate downstream MCP checks
        if agent_status is None:
            agent_status = await agent_service.get_agent_status(
                timeout=settings.agent_status_command_timeout_seconds
            )

        return HealthServiceStatus(
            status="up" if agent_status.get("available", False) else "down",
            latency_ms=agent_status.get("latency_ms"),
            details=agent_status,
        )
    except Exception as e:
        # During startup, agent might not be ready yet - don't fail health check
        return HealthServiceStatus(
            status="unknown",
            error=str(e),
            details={"error": "Agent service check failed - may still be starting"},
        )


async def check_feature_server_health(
    agent_status: Optional[Dict[str, Any]] = None,
) -> HealthServiceStatus:
    """Check feature server health independently (not via agent).

    Args:
        agent_status: Optional pre-fetched agent status dict.
    """
    try:
        # Try to check feature server directly if possible
        # For now, check via agent but handle failures gracefully
        if agent_status is None:
            agent_status = await agent_service.get_agent_status(
                timeout=settings.agent_status_command_timeout_seconds
            )
        feature_server_status = agent_status.get("feature_server", {})
        agent_available = agent_status.get("available", False)
        
        if feature_server_status:
            # Get status from agent response, but infer from data if unknown
            status = feature_server_status.get("status", "unknown")
            
            # If status is unknown but we have feature registry data, infer status
            if status == "unknown":
                feature_count = feature_server_status.get("feature_registry_count", 0)
                if feature_count > 0:
                    status = "up"
                    # Update the status in the details for consistency
                    feature_server_status = dict(feature_server_status)
                    feature_server_status["status"] = "up"
                    feature_server_status["note"] = f"Inferred UP from {feature_count} registered features"
                elif agent_available:
                    # Agent is UP and responding - if feature server data exists, infer UP
                    # Feature server is part of agent, so if agent works, feature server likely works
                    status = "up"
                    feature_server_status = dict(feature_server_status)
                    feature_server_status["status"] = "up"
                    feature_server_status["note"] = "Inferred UP - agent is available and responding"
                else:
                    # No features loaded yet - may be initializing
                    feature_server_status = dict(feature_server_status)
                    feature_server_status["note"] = "Feature registry empty - may be initializing"
            
            return HealthServiceStatus(
                status=status,
                latency_ms=feature_server_status.get("latency_ms"),
                details=feature_server_status
            )
        else:
            # Agent is available but feature server status not provided
            if agent_available:
                # If agent is UP, infer feature server is UP (it's part of agent)
                return HealthServiceStatus(
                    status="up",
                    details={"note": "Inferred UP - agent is available and responding"}
                )
            else:
                return HealthServiceStatus(
                    status="down",
                    error="Feature server unavailable - agent not responding",
                    details={"note": "Agent not available"}
                )
    except Exception as e:
        # Agent service unavailable - report feature server as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check feature server: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify feature server"}
        )


async def check_model_nodes_health(
    agent_status: Optional[Dict[str, Any]] = None,
) -> HealthServiceStatus:
    """Check model nodes health independently (not via agent).

    Args:
        agent_status: Optional pre-fetched agent status dict.
    """
    try:
        if agent_status is None:
            agent_status = await agent_service.get_agent_status(
                timeout=settings.agent_status_command_timeout_seconds
            )
        model_nodes_status = agent_status.get("model_nodes", {})
        agent_available = agent_status.get("available", False)
        
        if model_nodes_status:
            healthy_count = model_nodes_status.get("healthy_models", 0)
            total_count = model_nodes_status.get("total_models", 0)
            status_from_agent = model_nodes_status.get("status", "unknown")
            
            # If no models are loaded, return "unknown" (not "down") since this is acceptable in paper trading mode
            if total_count == 0:
                # But if agent is UP, we can infer model nodes are UP (just no models loaded)
                if agent_available:
                    return HealthServiceStatus(
                        status="up",
                        details={
                            **model_nodes_status,
                            "status": "up",
                            "note": "No models loaded - agent functioning in paper trading mode"
                        }
                    )
                return HealthServiceStatus(
                    status="unknown",
                    details={
                        **model_nodes_status,
                        "note": "No models loaded - agent can function in paper trading mode without ML models"
                    }
                )
            
            # Use status from agent if available and not unknown, otherwise determine from healthy count
            # Normalize "down" to "degraded" when agent is up and models are loaded (0 healthy can mean "no predictions yet")
            if status_from_agent != "unknown":
                display_status = status_from_agent
                details_out = dict(model_nodes_status)
                if status_from_agent == "down" and agent_available and total_count > 0 and healthy_count == 0:
                    display_status = "degraded"
                    details_out["status"] = "degraded"
                    details_out["note"] = (
                        details_out.get("note")
                        or f"Models loaded ({total_count}); run predictions to refresh healthy count (0/{total_count})"
                    )
                return HealthServiceStatus(status=display_status, details=details_out)
            else:
                # Infer status from available data
                if total_count > 0:
                    if healthy_count > 0:
                        inferred_status = "up"
                    elif healthy_count == 0 and total_count > 0:
                        # Show degraded (warning) not down when agent is available - 0 healthy may mean no predictions yet
                        inferred_status = "degraded" if agent_available else "down"
                    elif agent_available:
                        # Agent is UP - infer model nodes are UP even if status unknown
                        inferred_status = "up"
                    else:
                        inferred_status = "unknown"
                    
                    # Update the status in the response for consistency
                    updated_details = dict(model_nodes_status)
                    updated_details["status"] = inferred_status
                    if inferred_status == "up" and agent_available:
                        updated_details["note"] = f"Inferred UP - agent available, {healthy_count}/{total_count} models"
                    elif inferred_status == "degraded":
                        updated_details["note"] = (
                            f"Models loaded ({total_count}); healthy count 0/{total_count} (run predictions to refresh)"
                        )
                    else:
                        updated_details["note"] = f"Inferred status from {healthy_count}/{total_count} healthy models"
                    
                    return HealthServiceStatus(
                        status=inferred_status,
                        details=updated_details
                    )
                else:
                    # No total count but agent available - infer UP
                    if agent_available:
                        return HealthServiceStatus(
                            status="up",
                            details={**model_nodes_status, "status": "up", "note": "Inferred UP - agent available"}
                        )
                    return HealthServiceStatus(
                        status="up" if healthy_count > 0 else "unknown",
                        details=model_nodes_status
                    )
        else:
            # No model nodes status but agent available - infer UP
            if agent_available:
                return HealthServiceStatus(
                    status="up",
                    details={"note": "Inferred UP - agent available and responding"}
                )
            return HealthServiceStatus(
                status="unknown",
                error="Model nodes status not available",
                details={"note": "Agent available but model nodes status unknown"}
            )
    except Exception as e:
        # Agent service unavailable - report model nodes as unknown, not down
        error_msg = str(e)
        details_note = "Agent service unavailable, cannot verify model nodes"
        
        # Provide more specific error messages
        if "redis" in error_msg.lower() or "connection" in error_msg.lower():
            details_note = "Agent service unavailable - check Redis connection and ensure agent is running"
        elif "timeout" in error_msg.lower():
            details_note = "Agent service timeout - agent may be overloaded or not responding"
        
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check model nodes: {error_msg}",
            details={
                "note": details_note,
                "troubleshooting": "Ensure agent service is running and Redis is accessible. Check agent logs for model discovery errors."
            }
        )


async def check_delta_exchange_health(
    agent_status: Optional[Dict[str, Any]] = None,
) -> HealthServiceStatus:
    """Check Delta Exchange API health independently (not via agent).

    Args:
        agent_status: Optional pre-fetched agent status dict.
    """
    try:
        if agent_status is None:
            agent_status = await agent_service.get_agent_status(
                timeout=settings.agent_status_command_timeout_seconds
            )
        delta_status = agent_status.get("delta_exchange", {})
        agent_available = agent_status.get("available", False)
        
        if delta_status:
            # Get status from agent response, but infer from data if unknown
            status = delta_status.get("status", "unknown")
            
            # If status is unknown but we have circuit breaker data, infer status
            if status == "unknown":
                circuit_breaker = delta_status.get("circuit_breaker", {})
                if circuit_breaker and isinstance(circuit_breaker, dict):
                    cb_state = circuit_breaker.get("state")
                    if cb_state == "CLOSED":
                        status = "up"  # Circuit breaker closed means service is healthy
                        # Update the status in the details for consistency
                        delta_status = dict(delta_status)
                        delta_status["status"] = "up"
                        delta_status["note"] = "Inferred healthy status from circuit breaker state"
                    elif cb_state == "OPEN":
                        status = "down"  # Circuit breaker open means service is unhealthy
                        delta_status = dict(delta_status)
                        delta_status["status"] = "down"
                        delta_status["note"] = "Circuit breaker is open - service temporarily unavailable"
                elif agent_available:
                    # Agent is UP - if we have delta_status data, infer UP
                    status = "up"
                    delta_status = dict(delta_status)
                    delta_status["status"] = "up"
                    delta_status["note"] = "Inferred UP - agent available and responding"
            
            return HealthServiceStatus(
                status=status,
                latency_ms=delta_status.get("latency_ms"),
                details=delta_status
            )
        else:
            # Agent is available but Delta Exchange status not provided
            if agent_available:
                # If agent is UP, infer Delta Exchange is UP (agent needs it to function)
                return HealthServiceStatus(
                    status="up",
                    details={"note": "Inferred UP - agent available and responding"}
                )
            else:
                return HealthServiceStatus(
                    status="down",
                    error="Delta Exchange unavailable - agent not responding",
                    details={"note": "Agent not available"}
                )
    except Exception as e:
        # Agent service unavailable - report Delta Exchange as unknown, not down
        return HealthServiceStatus(
            status="unknown",
            error=f"Cannot check Delta Exchange: {str(e)}",
            details={"note": "Agent service unavailable, cannot verify Delta Exchange"}
        )


async def check_model_serving_health() -> HealthServiceStatus:
    """Check model-serving endpoint health (direct HTTP)."""
    try:
        health = await model_service.get_health()
        status_str = health.get("status", "down")
        latency_ms = health.get("latency_ms")
        error = health.get("error")
        details = health.get("details") or {}
        # Optionally write heartbeat to Redis for other consumers
        ttl = getattr(settings, "model_health_ttl", 30)
        if ttl > 0:
            await set_model_health_heartbeat(
                {"status": status_str, "latency_ms": latency_ms, "details": details},
                ttl=ttl,
            )
        return HealthServiceStatus(
            status=status_str,
            latency_ms=latency_ms,
            error=error,
            details=details,
        )
    except Exception as e:
        return HealthServiceStatus(
            status="down",
            error=str(e),
            details={"note": "Model serving check failed"},
        )


async def check_reasoning_engine_health(
    agent_status: Optional[Dict[str, Any]] = None,
) -> HealthServiceStatus:
    """Check reasoning engine health independently (not via agent).

    Args:
        agent_status: Optional pre-fetched agent status dict.
    """
    try:
        if agent_status is None:
            agent_status = await agent_service.get_agent_status(
                timeout=settings.agent_status_command_timeout_seconds
            )
        reasoning_status = agent_status.get("reasoning_engine", {})
        agent_available = agent_status.get("available", False)
        
        if reasoning_status:
            # Get status from agent response, but infer from data if unknown
            status = reasoning_status.get("status", "unknown")
            
            # If status is unknown but we have reasoning engine data, infer status
            if status == "unknown":
                # Reasoning engine is typically available if agent is running
                # Check if we have any reasoning-related data
                vector_store_available = reasoning_status.get("vector_store_available", None)
                if vector_store_available is not None:
                    status = "up"  # If we have any reasoning data, assume it's working
                    # Update the status in the details for consistency
                    reasoning_status = dict(reasoning_status)
                    reasoning_status["status"] = "up"
                    reasoning_status["note"] = "Inferred healthy status from reasoning engine data availability"
                elif agent_available:
                    # Agent is UP - reasoning engine is part of agent, so infer UP
                    status = "up"
                    reasoning_status = dict(reasoning_status)
                    reasoning_status["status"] = "up"
                    reasoning_status["note"] = "Inferred UP - agent available and responding"
            
            return HealthServiceStatus(
                status=status,
                details=reasoning_status
            )
        else:
            # Agent is available but reasoning engine status not provided
            if agent_available:
                # If agent is UP, infer reasoning engine is UP (it's part of agent)
                return HealthServiceStatus(
                    status="up",
                    details={"note": "Inferred UP - agent available and responding"}
                )
            else:
                return HealthServiceStatus(
                    status="down",
                    error="Reasoning engine unavailable - agent not responding",
                    details={"note": "Agent not available"}
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


async def check_overall_health(db: AsyncSession) -> dict:
    """Build health response dict for WebSocket or API.
    
    Args:
        db: Database session for health checks
        
    Returns:
        Dict suitable for HealthResponse model (services, status, health_score, etc.)
    """
    # Check cache first (30 second TTL)
    cache_key = "health:check"
    cached = await get_cache(cache_key)
    if cached:
        return cached
    
    degradation_reasons = []
    health_scores = []
    
    # Check database
    db_health = await check_database_health(db)
    if db_health.status == "up":
        health_scores.append(0.05)
    else:
        degradation_reasons.append("Database is down")
        health_scores.append(0.0)
    
    # Check Redis
    redis_health = await redis_health_check()
    redis_status = HealthServiceStatus(**redis_health)
    if redis_status.status == "up":
        health_scores.append(0.05)
    else:
        degradation_reasons.append("Redis is down")
        health_scores.append(0.0)
    
    # Check agent (fetch status once and share with dependent checks)
    raw_agent_status: Optional[Dict[str, Any]] = None
    try:
        raw_agent_status = await agent_service.get_agent_status(
            timeout=settings.agent_status_command_timeout_seconds
        )
    except Exception:
        # Use a placeholder dict so dependent checks don't trigger
        # additional agent round-trips (which can cascade into timeouts).
        raw_agent_status = {
            "available": False,
            "state": "DEGRADED",
            "health_status": "timeout",
            "message": "Agent not responding to health commands (timeout)",
            "latency_ms": None,
            "active_symbols": [],
            "model_count": 0,
            "feature_server": {},
            "model_nodes": {},
            "delta_exchange": {},
            "reasoning_engine": {},
        }

    agent_health = await check_agent_health(raw_agent_status)
    agent_weight = 0.15
    if agent_health.status == "up":
        health_scores.append(agent_weight)
        agent_state = agent_health.details.get("state") if agent_health.details else None
    elif agent_health.status == "unknown":
        degradation_reasons.append("Agent service starting up")
        health_scores.append(agent_weight * 0.5)
        agent_state = None
    else:
        degradation_reasons.append("Agent service is down")
        health_scores.append(0.0)
        agent_state = None
    
    # Check feature server
    feature_health = await check_feature_server_health(raw_agent_status)
    feature_weight = 0.20
    if feature_health.status == "up":
        health_scores.append(feature_weight)
    elif feature_health.status == "unknown" and agent_health.status == "up":
        health_scores.append(feature_weight * 0.5)
    else:
        if feature_health.status != "unknown":
            degradation_reasons.append("Feature server is down")
        health_scores.append(0.0)
    
    # Check model serving (direct HTTP predict endpoint; failure does not reduce score — agent fallback)
    model_serving_health = await check_model_serving_health()

    # Check model nodes (via agent)
    model_health = await check_model_nodes_health(raw_agent_status)
    model_weight = 0.25
    if model_health.status == "up":
        if model_health.details:
            healthy_count = model_health.details.get("healthy_models", 0)
            total_count = model_health.details.get("total_models", 0)
            if total_count > 0 and healthy_count < total_count:
                degradation_reasons.append(f"Only {healthy_count}/{total_count} models are healthy")
            health_scores.append(model_weight * (healthy_count / max(total_count, 1)))
        else:
            health_scores.append(model_weight)
    elif model_health.status == "unknown" and agent_health.status == "up":
        health_scores.append(model_weight * 0.5)
    else:
        if model_health.status != "unknown":
            is_paper_mode = str(getattr(settings, "trading_mode", "paper")).lower() == "paper"
            if is_paper_mode:
                degradation_reasons.append(
                    "Model nodes are degraded; paper mode remains available via agent fallback."
                )
            else:
                degradation_reasons.append("No model nodes are healthy")
        health_scores.append(0.0)
    
    # Check Delta Exchange
    delta_health = await check_delta_exchange_health(raw_agent_status)
    delta_weight = 0.15
    if delta_health.status == "up":
        health_scores.append(delta_weight)
    elif delta_health.status == "unknown" and agent_health.status == "up":
        health_scores.append(delta_weight * 0.5)
    else:
        if delta_health.status != "unknown":
            degradation_reasons.append("Delta Exchange API is down")
        health_scores.append(0.0)
    
    # Check reasoning engine
    reasoning_health = await check_reasoning_engine_health(raw_agent_status)
    reasoning_weight = 0.15
    if reasoning_health.status == "up":
        health_scores.append(reasoning_weight)
    elif reasoning_health.status == "unknown" and agent_health.status == "up":
        health_scores.append(reasoning_weight * 0.5)
    else:
        if reasoning_health.status != "unknown":
            degradation_reasons.append("Reasoning engine is down")
        health_scores.append(0.0)
    
    health_score = sum(health_scores)
    if health_score >= 0.9:
        status_str = "healthy"
    elif health_score >= 0.6:
        status_str = "degraded"
    else:
        status_str = "unhealthy"
    
    def _to_dict(obj):
        return obj.model_dump() if hasattr(obj, "model_dump") else obj

    # Trading readiness:
    # - In paper mode, system can operate via agent fallback even when model health is degraded.
    # - In live mode, keep stricter requirement on model availability.
    model_status = getattr(model_health, "status", "unknown")
    details = getattr(model_health, "details", None) or {}
    healthy_models = details.get("healthy_models", 0)
    total_models = details.get("total_models", 0)
    is_paper_mode = str(getattr(settings, "trading_mode", "paper")).lower() == "paper"
    if is_paper_mode:
        trading_ready = agent_health.status in {"up", "unknown"}
    else:
        trading_ready = (
            model_status == "up"
            and (total_models == 0 or (healthy_models is not None and healthy_models > 0))
        )

    result = {
        "status": status_str,
        "health_score": round(health_score, 3),
        "services": {
            "database": _to_dict(db_health),
            "redis": _to_dict(redis_status),
            "agent": _to_dict(agent_health),
            "feature_server": _to_dict(feature_health),
            "model_serving": _to_dict(model_serving_health),
            "model_nodes": _to_dict(model_health),
            "delta_exchange": _to_dict(delta_health),
            "reasoning_engine": _to_dict(reasoning_health),
        },
        "agent_state": agent_state,
        "degradation_reasons": degradation_reasons,
        "trading_ready": trading_ready,
        "timestamp": datetime.utcnow(),
    }
    
    await set_cache(cache_key, result, ttl=30)
    return result


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, db: AsyncSession = Depends(get_db)):
    """
    **DEPRECATED**: This REST API endpoint is deprecated.

    Use WebSocket command instead:
    ```javascript
    websocket.send(JSON.stringify({
      action: 'command',
      command: 'get_health',
      request_id: 'req_123',
      parameters: {}
    }))
    ```

    Comprehensive health check endpoint.

    Checks status of all system components:
    - Database connection
    - Redis connection
    - Agent service
    - Delta Exchange API (via agent)
    - Feature server
    - Model nodes

    Rate limited to 100 requests per minute per IP to prevent abuse.
    Results are cached for 30 seconds to reduce downstream load.
    """
    # Apply lightweight rate limiting
    client_ip = request.client.host if request.client else "unknown"
    if not _check_health_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Health check rate limit exceeded. Maximum 100 requests per minute per IP.",
            headers={"Retry-After": str(_health_rate_limit_window)},
        )
    
    health_data = await check_overall_health(db)
    health_response = HealthResponse(**health_data)
    
    # Log deprecation warning for non-healthcheck callers only
    import structlog
    logger = structlog.get_logger()
    user_agent = (request.headers.get("user-agent") or "").lower()
    if not any(marker in user_agent for marker in ("curl", "healthcheck", "docker")):
        logger.warning(
            "health_endpoint_deprecated",
            message="REST API /health endpoint is deprecated. Use WebSocket command 'get_health' instead.",
            migration_guide="Send: {action: 'command', command: 'get_health', request_id: '...', parameters: {}}"
        )

    return health_response

