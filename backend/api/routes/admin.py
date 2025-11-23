"""
Admin and control endpoints.

Provides agent control and system administration functions.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime

from backend.api.models.requests import AgentControlRequest
from backend.api.models.responses import AgentStatusResponse
from backend.services.agent_service import agent_service
from backend.api.middleware.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/agent/status", response_model=AgentStatusResponse)
async def get_agent_status():
    """
    Get agent status.
    
    Returns current agent state and health information.
    """
    
    try:
        status_data = await agent_service.get_agent_status()
        
        if not status_data:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return AgentStatusResponse(**status_data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent status: {str(e)}"
        )


@router.post("/agent/control")
async def control_agent(request: AgentControlRequest):
    """
    Control agent (start, stop, pause, resume, restart).
    
    Sends control command to agent service.
    """
    
    try:
        result = await agent_service.control_agent(
            action=request.action,
            parameters=request.parameters or {}
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return {
            "status": "success",
            "action": request.action,
            "agent_state": result.get("state"),
            "message": result.get("message", ""),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to control agent: {str(e)}"
        )


@router.post("/agent/start")
async def start_agent():
    """
    Start the trading agent.
    
    Shortcut endpoint for starting the agent.
    """
    
    try:
        result = await agent_service.control_agent(action="start", parameters={})
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return {
            "status": "started",
            "agent_state": result.get("state", "UNKNOWN"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start agent: {str(e)}"
        )


@router.post("/agent/stop")
async def stop_agent():
    """
    Stop the trading agent.
    
    Shortcut endpoint for stopping the agent.
    """
    
    try:
        result = await agent_service.control_agent(action="stop", parameters={})
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return {
            "status": "stopped",
            "agent_state": result.get("state", "STOPPED"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop agent: {str(e)}"
        )


@router.post("/agent/emergency-stop")
async def emergency_stop():
    """
    Emergency stop - immediately halt all trading.
    
    Immediately stops all trading operations.
    """
    
    try:
        result = await agent_service.control_agent(action="emergency_stop", parameters={})
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Agent service unavailable"
            )
        
        return {
            "status": "emergency_stopped",
            "agent_state": result.get("state", "EMERGENCY_STOP"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to emergency stop agent: {str(e)}"
        )

