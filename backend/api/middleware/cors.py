"""
CORS middleware configuration.

CORS is already configured in main.py using FastAPI's CORSMiddleware.
This file exists for documentation and potential custom CORS logic.
"""

from fastapi.middleware.cors import CORSMiddleware
from backend.core.config import settings

# CORS configuration is handled in backend/api/main.py
# This file is for reference and potential custom CORS logic

def get_cors_middleware():
    """Get CORS middleware with configuration."""
    
    return CORSMiddleware(
        app=None,  # Set in main.py
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )

