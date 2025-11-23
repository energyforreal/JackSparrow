"""
Feature service client.

Provides client for MCP Feature Server.
"""

from typing import Optional, Dict, Any, List
import httpx
import asyncio
import structlog

from backend.core.config import settings
from backend.core.redis import get_cache, set_cache

logger = structlog.get_logger()


class FeatureService:
    """Client for MCP Feature Server."""
    
    def __init__(self):
        """Initialize feature service."""
        self.base_url = settings.feature_server_url
        self.timeout = 30.0
    
    async def get_features(
        self,
        symbol: str,
        feature_names: List[str],
        version: str = "latest"
    ) -> Optional[Dict[str, Any]]:
        """Get features from MCP Feature Server."""
        
        # Check cache first
        cache_key = f"features:{symbol}:{':'.join(sorted(feature_names))}:{version}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/features",
                    json={
                        "symbol": symbol,
                        "feature_names": feature_names,
                        "version": version
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # Cache result (short TTL for features)
                    await set_cache(cache_key, data, ttl=30)
                    return data
                else:
                    logger.error(
                        "feature_service_error",
                        status_code=response.status_code,
                        response_text=response.text[:200],  # Limit log size
                        symbol=symbol,
                        feature_names=feature_names
                    )
                    return None
                    
        except httpx.TimeoutException:
            logger.warning(
                "feature_service_timeout",
                symbol=symbol,
                feature_names=feature_names,
                timeout=self.timeout
            )
            return None
        except Exception as e:
            logger.error(
                "feature_service_get_features_failed",
                symbol=symbol,
                feature_names=feature_names,
                error=str(e),
                exc_info=True
            )
            return None


# Global feature service instance
feature_service = FeatureService()

