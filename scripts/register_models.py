"""
CLI utility to request the agent to register pending models.

When MODEL_AUTO_REGISTER is disabled, discovered models are queued internally.
This script sends a command to the running agent (via Redis) instructing it to
register all pending models or a subset specified on the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import List, Optional

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.core.config import settings
from agent.core.redis_config import get_redis

logger = structlog.get_logger()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register pending ML models with the running agent."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Specific model names to register (defaults to all pending models).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Seconds to wait for agent response (default: 30).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds between response polls (default: 0.5).",
    )
    return parser.parse_args()


async def _send_register_command(
    models: Optional[List[str]],
    timeout: int,
    poll_interval: float,
) -> Optional[dict]:
    """Send register_models command via Redis and await response."""
    redis = await get_redis()
    if redis is None:
        raise RuntimeError("Redis unavailable. Ensure Redis is running and reachable.")

    request_id = str(uuid.uuid4())
    message = {
        "request_id": request_id,
        "command": "register_models",
        "parameters": {"models": models} if models else {},
        "timestamp": time.time(),
    }

    await redis.lpush(settings.agent_command_queue, json.dumps(message))

    response_key = f"response:{request_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        raw = await redis.get(response_key)
        if raw:
            return json.loads(raw)
        await asyncio.sleep(poll_interval)

    return None


async def _run_cli() -> int:
    args = _parse_args()

    try:
        response = await _send_register_command(
            models=args.models,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
    except Exception as exc:  # pragma: no cover - CLI wiring
        logger.error("register_models_command_failed", error=str(exc))
        return 1

    if not response:
        logger.error("register_models_timeout", timeout=args.timeout)
        return 1

    if response.get("success"):
        data = response.get("data", {})
        print(json.dumps(data, indent=2))
        return 0

    logger.error("register_models_error", error=response.get("error"))
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_cli()))

