"""
Feature service client.

Provides client for MCP Feature Server.
"""

from typing import Optional, Dict, Any, List
import httpx
import asyncio

from backend.core.config import settings
from backend.core.redis import get_cache, set_cache


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
                    print(f"Feature server error: {response.status_code} - {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            print("Feature server timeout")
            return None
        except Exception as e:
            print(f"Error getting features: {e}")
            return None


# Global feature service instance
feature_service = FeatureService()

