"""
Authentication middleware.

Provides JWT token authentication for protected endpoints.
"""

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from typing import Optional

from backend.core.config import settings

security = HTTPBearer(auto_error=False)


async def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = None) -> Optional[str]:
    """Verify JWT token and return user ID."""
    
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        
        if user_id is None:
            return None
        
        return user_id
        
    except JWTError:
        return None


async def verify_api_key(request: Request) -> bool:
    """Verify API key from header."""
    
    api_key = request.headers.get("X-API-Key")
    
    if not api_key:
        return False
    
    return api_key == settings.api_key


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = security
) -> Optional[dict]:
    """Get current authenticated user."""
    
    # Try JWT token first
    user_id = await verify_token(credentials)
    if user_id:
        return {"user_id": user_id, "auth_type": "jwt"}
    
    # Try API key
    if await verify_api_key(request):
        return {"user_id": "api_key", "auth_type": "api_key"}
    
    # No authentication found
    return None


async def require_auth(request: Request):
    """Require authentication for protected endpoints."""
    
    user = await get_current_user(request)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user

