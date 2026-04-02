"""
Periodic retraining scheduler (local automation).

This module evaluates recent `trade_outcomes` and, when performance drops below
configured thresholds, runs a **user-provided** retraining command.

It does not assume a specific training pipeline; the configured command must
export a metadata-driven bundle compatible with `agent/models/model_discovery.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
import asyncio
import math
from typing import Any, Dict, List
import os
import json
import shlex
import subprocess

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agent.core.config import settings

logger = structlog.get_logger()
_RETRAIN_LOCK = asyncio.Lock()


def _sync_database_url(url: str) -> str:
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


@dataclass
class RetrainingScheduler:
    """Evaluate outcomes and trigger a local retrain command."""

    model_base: str = "./agent/model_storage"

    def _state_path(self) -> Path:
        p = str(getattr(settings, "retraining_state_path", "retraining_state.json") or "retraining_state.json")
        path = Path(p)
        if path.is_absolute():
            return path
        logs_root = os.environ.get("LOGS_ROOT")
        if logs_root:
            return Path(logs_root) / path
        return path

    def _load_state(self) -> Dict[str, Any]:
        path = self._state_path()
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("retraining_state_load_failed", path=str(path), error=str(e))
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            logger.warning("retraining_state_save_failed", path=str(path), error=str(e))

    def _cooldown_ok(self) -> bool:
        cooldown_min = int(getattr(settings, "retraining_cooldown_minutes", 360) or 360)
        if cooldown_min <= 0:
            return True
        state = self._load_state()
        last = state.get("last_retrain_at")
        if not isinstance(last, str) or not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except Exception:
            return True
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_dt >= timedelta(minutes=cooldown_min)

    async def _fetch_recent_outcomes(
        self, database_url: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Load recent trade_outcomes rows (sync DB in thread)."""
        import asyncio

        def _sync_fetch() -> List[Dict[str, Any]]:
            engine = create_engine(_sync_database_url(database_url), poolclass=NullPool)
            try:
                with engine.connect() as conn:
                    result = conn.execute(
                        text(
                            """
                            SELECT pnl, closed_at
                            FROM trade_outcomes
                            ORDER BY closed_at DESC
                            LIMIT :lim
                            """
                        ),
                        {"lim": limit},
                    )
                    return [dict(row._mapping) for row in result]
            finally:
                engine.dispose()

        return await asyncio.to_thread(_sync_fetch)

    async def should_retrain(self, _redis_client: Any, db_url: str) -> bool:
        """Return True when performance over recent outcomes is below thresholds."""
        if not getattr(settings, "retraining_scheduler_enabled", False):
            return False
        # If no command is configured, do not evaluate triggers (avoids repetitive warn spam).
        cmd = str(getattr(settings, "retraining_command", "") or "").strip()
        if not cmd:
            return False
        if not db_url:
            return False
        if not self._cooldown_ok():
            return False

        window = int(getattr(settings, "retraining_rolling_window", 100) or 100)
        min_rows = int(getattr(settings, "retraining_min_closed_trades", 50) or 50)
        window = max(10, window)
        min_rows = max(10, min_rows)

        try:
            rows = await self._fetch_recent_outcomes(db_url, window)
        except Exception as e:
            logger.warning("retraining_fetch_failed", error=str(e), exc_info=True)
            return False

        if len(rows) < min_rows:
            logger.debug(
                "retraining_skipped_insufficient_outcomes",
                row_count=len(rows),
                min_rows=min_rows,
            )
            return False

        pnl_values = [_safe_float(r.get("pnl"), 0.0) for r in rows]
        wins = sum(1 for v in pnl_values if v > 0)
        win_rate = wins / max(len(pnl_values), 1)
        gross_profit = sum(v for v in pnl_values if v > 0)
        gross_loss = abs(sum(v for v in pnl_values if v < 0))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else (999.0 if gross_profit > 0 else 1.0)
        )

        win_floor = float(getattr(settings, "retraining_win_rate_threshold", 0.45) or 0.45)
        pf_floor = float(getattr(settings, "retraining_profit_factor_threshold", 0.90) or 0.90)
        should = win_rate < win_floor or profit_factor < pf_floor

        logger.info(
            "retraining_trigger_evaluated",
            sample_size=len(rows),
            win_rate=win_rate,
            profit_factor=profit_factor,
            win_floor=win_floor,
            profit_factor_floor=pf_floor,
            should_retrain=should,
        )
        return should

    async def run(self, _redis_client: Any) -> Dict[str, Any]:
        """Run configured retraining command (best-effort) and record state."""
        if not getattr(settings, "retraining_scheduler_enabled", False):
            return {"executed": False, "success": False, "reason": "scheduler_disabled"}
        cmd = str(getattr(settings, "retraining_command", "") or "").strip()
        if not cmd:
            logger.warning(
                "retraining_command_missing",
                message="RETRAINING_COMMAND is empty; scheduler cannot execute retraining.",
            )
            return {"executed": False, "success": False, "reason": "missing_command"}

        try:
            argv = shlex.split(cmd)
        except Exception:
            argv = [cmd]

        logger.info("retraining_starting", command=cmd)

        def _run_sync() -> subprocess.CompletedProcess[str]:
            return subprocess.run(argv, capture_output=True, text=True, check=False)

        async with _RETRAIN_LOCK:
            try:
                proc = await asyncio.to_thread(_run_sync)
            except Exception as e:
                logger.warning("retraining_subprocess_failed", error=str(e), exc_info=True)
                return {"executed": True, "success": False, "reason": "subprocess_failed"}

            state = self._load_state()
            state["last_retrain_at"] = datetime.now(timezone.utc).isoformat()
            state["last_retrain_command"] = cmd
            state["last_retrain_exit_code"] = int(getattr(proc, "returncode", -1))
            state["last_retrain_stdout_tail"] = (proc.stdout or "")[-2000:]
            state["last_retrain_stderr_tail"] = (proc.stderr or "")[-2000:]
            self._save_state(state)

            if proc.returncode != 0:
                logger.warning(
                    "retraining_failed",
                    exit_code=proc.returncode,
                    stdout_tail=state["last_retrain_stdout_tail"],
                    stderr_tail=state["last_retrain_stderr_tail"],
                )
                return {
                    "executed": True,
                    "success": False,
                    "reason": "nonzero_exit",
                    "exit_code": proc.returncode,
                }

            logger.info(
                "retraining_completed",
                exit_code=proc.returncode,
                stdout_tail=state["last_retrain_stdout_tail"],
            )
            consolidated_found = True
            if bool(getattr(settings, "single_model_mode_enabled", False)):
                pattern = str(
                    getattr(
                        settings,
                        "consolidated_model_metadata_glob",
                        "metadata_BTCUSD_consolidated*.json",
                    )
                    or "metadata_BTCUSD_consolidated*.json"
                )
                model_dir = Path(str(getattr(settings, "model_dir", self.model_base) or self.model_base))
                recursive = bool(getattr(settings, "model_discovery_recursive", True))
                files = list(model_dir.rglob(pattern) if recursive else model_dir.glob(pattern))
                consolidated_found = len(files) > 0
                if not consolidated_found:
                    logger.warning(
                        "retraining_consolidated_artifact_missing",
                        model_dir=str(model_dir),
                        metadata_pattern=pattern,
                        message=(
                            "Retraining completed but no consolidated metadata artifact found. "
                            "Ensure RETRAINING_COMMAND exports consolidated metadata/artifacts."
                        ),
                    )
            return {
                "executed": True,
                "success": True,
                "exit_code": proc.returncode,
                "stdout_tail": state["last_retrain_stdout_tail"],
                "consolidated_artifact_found": consolidated_found,
            }
