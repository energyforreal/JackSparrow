"""Algorithmic decision path. No model registry and no order placement.

Orders stay in the execution engine and remain blocked unless
``ALGORITHMIC_ORDERS_ENABLED`` is true.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

import pandas as pd
import structlog

from agent.events.schemas import PolicyVerdict
from research.swinging.contract import ALGO_DECISION_PATH, RESOLUTIONS
from research.swinging.decision_contract import build_algorithmic_decision
from research.swinging.mtf_score import score_frames

logger = structlog.get_logger()

_CANDLE_PLAN = (
    ("5m", 300, 400),
    ("15m", 900, 300),
    ("1h", 3600, 250),
    ("4h", 14_400, 220),
)


def _reason_codes(scored: Mapping[str, Any]) -> list[str]:
    quality = str(scored.get("quality") or "none")
    if quality == "high":
        codes = ["algorithmic_high_quality"]
    elif quality == "qualified":
        codes = ["algorithmic_qualified"]
    else:
        codes = ["algorithmic_hold"]
    invalidation = str(scored.get("invalidation") or "")
    if invalidation:
        codes.append(invalidation)
    return codes


async def load_algorithmic_frames(symbol: str) -> Dict[str, pd.DataFrame]:
    """Fetch closed Delta candles for the four algorithmic timeframes.

    Args:
        symbol: Instrument, normally ``BTCUSD``.

    Returns:
        OHLCV frames keyed by resolution. The public candle host matches the
        rest of the market-frame loader.
    """
    from agent.core.market_frames import _fetch_ohlcv_df, get_public_candle_client

    client = get_public_candle_client()
    frames: Dict[str, pd.DataFrame] = {}
    for resolution, bar_seconds, count in _CANDLE_PLAN:
        frames[resolution] = await _fetch_ohlcv_df(
            client,
            symbol,
            resolution,
            bar_seconds,
            count,
        )
    return frames


async def evaluate_algorithmic_prediction(
    *,
    symbol: str,
    context: Dict[str, Any] | None,
    delta_client: Any,
    t0: float,
) -> Dict[str, Any]:
    """Score 4h, 1h, 15m, and 5m structure and return a policy verdict.

    The clock scores the last bar that has already closed. A still-forming
    5-minute candle in the feed does not zero the score.

    Args:
        symbol: Trading symbol.
        context: Optional ``algo_frames`` override. Live calls fetch candles.
        delta_client: Unused. Kept so the call shape matches the other paths.
        t0: ``perf_counter`` timestamp from the orchestrator.

    Returns:
        Orchestrator result with ``policy_verdict``. ``error`` is set only when
        scoring itself fails.
    """
    _ = delta_client
    context = context or {}
    supplied = context.get("algo_frames")
    try:
        if isinstance(supplied, Mapping) and all(name in supplied for name in RESOLUTIONS):
            frames = {name: supplied[name] for name in RESOLUTIONS}
        else:
            frames = await load_algorithmic_frames(symbol)
        as_of = context.get("as_of") or datetime.now(timezone.utc)
        scored = score_frames(
            frames,
            include_engine_a=bool(context.get("include_engine_a", True)),
            as_of=as_of,
            now=as_of,
        )
    except Exception as exc:
        logger.error(
            "algorithmic_decision_failed",
            symbol=symbol,
            error=str(exc),
            exc_info=True,
        )
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "error": str(exc),
            "error_code": "ALGORITHMIC_SCORE_FAILED",
            "decision": {"signal": "HOLD", "confidence": 0.0, "position_size": 0.0},
        }
    signal = str(scored["signal"])
    confidence = float(scored["confidence"])
    reasons = _reason_codes(scored)
    trading_decision = build_algorithmic_decision(
        symbol=symbol,
        scored=scored,
        reasons=reasons,
    )
    verdict = PolicyVerdict(
        signal=signal,
        confidence=confidence,
        position_size=0.0,
        reason_codes=reasons,
        adopted_ml_candidate=False,
    )
    chain_id = trading_decision["decision_id"]
    conclusion = (
        f"algorithmic {scored['quality']} {scored['action']} "
        f"score={scored['score']:.1f} invalidation={scored.get('invalidation') or 'none'}"
    )
    execution_plan = {
        "atr_14": scored.get("atr"),
        "stop_loss": trading_decision["risk"].get("stop_loss"),
        "take_profit": trading_decision["risk"].get("take_profit"),
        "entry": trading_decision.get("entry"),
    }
    market_context = {
        "decision_path": ALGO_DECISION_PATH,
        "closed_bar_index": scored.get("bar_index"),
        "features": {"atr_14": scored.get("atr")},
        "algo_score": scored.get("score"),
        "algo_quality": scored.get("quality"),
        "algo_components": scored.get("components"),
        "invalidation": scored.get("invalidation"),
        "algo_signal_validated": scored.get("action") in ("long", "short"),
        "candle_timestamp": scored.get("decision_time"),
        "timeframes": trading_decision["market_context"],
        "decision_id": trading_decision["decision_id"],
        "support_zones": trading_decision.get("support_zones") or [],
        "resistance_zones": trading_decision.get("resistance_zones") or [],
        "active_patterns": trading_decision.get("active_patterns") or [],
        "execution_plan": execution_plan,
    }
    result = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc),
        "error": None,
        "model_predictions": [],
        "market_context": market_context,
        "reasoning": {
            "chain_id": chain_id,
            "steps": [
                {
                    "step": "algorithmic_mtf_score",
                    "score": scored.get("score"),
                    "components": scored.get("components"),
                    "invalidation": scored.get("invalidation"),
                    "decision_id": trading_decision["decision_id"],
                }
            ],
            "conclusion": conclusion,
            "final_confidence": confidence,
            "signal_strength": confidence,
        },
        "decision": {
            "signal": signal,
            "position_size": 0.0,
            "confidence": confidence,
            "reasoning": conclusion,
            "policy_reason_codes": list(verdict.reason_codes),
        },
        "policy_verdict": verdict.model_dump(mode="json"),
        "trading_decision": trading_decision,
        "inference_latency_ms": (time.perf_counter() - t0) * 1000.0,
    }
    logger.info(
        "algorithmic_decision_complete",
        symbol=symbol,
        signal=signal,
        decision_id=trading_decision["decision_id"],
        score=scored.get("score"),
        quality=scored.get("quality"),
        invalidation=scored.get("invalidation"),
        decision_path=ALGO_DECISION_PATH,
    )
    return result
