"""
Periodic retraining scheduler (scaffolding).

Full automation should wait until prediction_audit + trade_outcomes pipelines are
healthy and feature parity gates pass in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import structlog

from agent.core.config import settings

logger = structlog.get_logger()


@dataclass
class RetrainingScheduler:
    """Gate future automated retrains on data volume and validation hooks."""

    min_new_candles: int = 2000
    model_base: str = "./agent/model_storage"

    async def should_retrain(self, _redis_client: Any, _db_url: str) -> bool:
        """Return True when enough new candles exist (placeholder)."""
        _ = settings  # reserved for future env-driven toggles
        logger.debug("retraining_scheduler_should_retrain_not_implemented")
        return False

    async def run(self, _redis_client: Any) -> Optional[str]:
        """Run training subprocess and promote model dir (placeholder)."""
        logger.info(
            "retraining_scheduler_run_skipped",
            message="Scaffolding only — enable after observability + parity gates pass.",
        )
        return None
