"""Retraining scheduler stub — ML training removed (NO-ML branch)."""

from __future__ import annotations

from typing import Any, Dict, Optional


class RetrainingScheduler:
    """No-op scheduler retained for agent loop compatibility."""

    async def should_retrain(self, *_args: Any, **_kwargs: Any) -> bool:
        return False

    async def run(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"success": False, "reason": "ml_retraining_removed"}
