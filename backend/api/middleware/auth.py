"""
Authentication middleware.

Provides JWT token authentication for protected endpoints.
"""

from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from typing import Optional
import secrets

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
    import structlog
    
    logger = structlog.get_logger()
    api_key = request.headers.get("X-API-Key")
    
    if not api_key:
        logger.debug(
            "api_key_missing",
            service="backend",
            endpoint=request.url.path,
            headers=dict(request.headers)
        )
        return False
    
    # Compare securely to prevent timing attacks
    is_valid = secrets.compare_digest(api_key, settings.api_key)
    
    if not is_valid:
        logger.warning(
            "api_key_invalid",
            service="backend",
            endpoint=request.url.path,
            provided_key_prefix=api_key[:8] + "..." if len(api_key) > 8 else "***",
            expected_key_prefix=settings.api_key[:8] + "..." if len(settings.api_key) > 8 else "***"
        )
    
    return is_valid


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> Optional[dict]:
    """Get current authenticated user."""
    
    # Extract credentials if not provided
    if credentials is None:
        credentials = await security(request)
    
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
    import structlog
    
    logger = structlog.get_logger()
    
    # Extract credentials using security dependency
    credentials = await security(request)
    user_id = await verify_token(credentials)
    
    # Try API key if JWT fails
    if not user_id:
        api_key_valid = await verify_api_key(request)
        if api_key_valid:
            logger.debug(
                "auth_success_api_key",
                service="backend",
                endpoint=request.url.path
            )
            return {"user_id": "api_key", "auth_type": "api_key"}
        
        # Check if any authentication was attempted
        has_auth_header = request.headers.get("Authorization") is not None
        has_api_key = request.headers.get("X-API-Key") is not None
        
        logger.warning(
            "auth_failed",
            service="backend",
            endpoint=request.url.path,
            has_auth_header=has_auth_header,
            has_api_key=has_api_key,
            client_ip=request.client.host if request.client else None
        )
        
        if has_auth_header:
            detail = "Invalid or expired authentication token. Please provide a valid JWT token or API key."
        elif has_api_key:
            detail = "Invalid API key. Please check your X-API-Key header matches the API_KEY in your .env file."
        else:
            detail = "Authentication required. Please provide either a Bearer token (Authorization header) or an API key (X-API-Key header)."
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.debug(
        "auth_success_jwt",
        service="backend",
        endpoint=request.url.path
    )
    return {"user_id": user_id, "auth_type": "jwt"}

