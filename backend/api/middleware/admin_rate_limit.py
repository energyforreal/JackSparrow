"""In-memory rate limiting for admin control endpoints."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, Request, status

_admin_rate_limit: Dict[str, List[float]] = defaultdict(list)
_ADMIN_RATE_LIMIT_REQUESTS = 5
_ADMIN_RATE_LIMIT_WINDOW = 60


def enforce_admin_rate_limit(request: Request) -> None:
    """Allow at most 5 admin requests per minute per client IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - _ADMIN_RATE_LIMIT_WINDOW
    hits = [t for t in _admin_rate_limit[client_ip] if t >= window_start]
    if len(hits) >= _ADMIN_RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Admin rate limit exceeded (5 requests per minute).",
            headers={"Retry-After": str(_ADMIN_RATE_LIMIT_WINDOW)},
        )
    hits.append(now)
    _admin_rate_limit[client_ip] = hits
