"""
System routes for time synchronization and system information.
"""

from fastapi import APIRouter
from backend.services.time_service import time_service

router = APIRouter()


@router.get("/system/time")
async def get_system_time():
    """Get current server time for synchronization.
    
    Returns:
        Server time information including ISO format timestamp and milliseconds
    """
    return time_service.get_time_info()

