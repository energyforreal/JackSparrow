"""Slim transformer-only decision path for MCP orchestrator."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.v43_market_frames import closed_5m_bar_index, fetch_v43_market_frames
from agent.data.feature_server import FeatureQuality, MCPFeature, MCPFeatureResponse
from agent.events.schemas import PolicyVerdict
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelRequest,
    NoHealthyModelPredictionsError,
    NoModelsRegisteredError,
)
from agent.models.transformer_context_builder import map_prediction_to_signal

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})


def _resolve_threshold(bundle_metadata: Dict[str, Any]) -> float:
    override = getattr(settings, "transformer_signal_threshold", None)
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    return float(bundle_metadata.get("default_threshold") or 0.005)


def _default_position_size(confidence: float) -> float:
    max_pct = float(getattr(settings, "max_position_size", 0.1) or 0.1)
    if confidence <= 0:
        return 0.0
    return float(max(0.01, min(max_pct, max_pct * confidence)))


def _build_reasoning_chain(
    *,
    symbol: str,
    signal: str,
    confidence: float,
    future_return: float,
    threshold: float,
    vol_regime: str,
    regime: str,
    model_predictions: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    reason_codes: List[str],
) -> Dict[str, Any]:
    chain_id = str(uuid.uuid4())
    conclusion = (
        f"Transformer: {signal} "
        f"(future_return={future_return:.5f}, thr={threshold:.5f}, "
        f"vol_regime={vol_regime}, regime={regime})"
    )
    return {
        "chain_id": chain_id,
        "conclusion": conclusion,
        "final_confidence": float(confidence),
        "signal_strength": signal if signal in _ENTRY_SIGNALS else "HOLD",
        "steps": [
            {
                "step_number": 1,
                "step_name": "transformer_inference",
                "description": conclusion,
                "evidence": [
                    f"symbol={symbol}",
                    f"future_return={future_return:.5f}",
                    f"threshold={threshold:.5f}",
                    f"vol_regime={vol_regime}",
                    f"reason_codes={','.join(reason_codes)}",
                ],
                "confidence": float(confidence),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "model_predictions": model_predictions,
        "market_context": market_context,
    }


def _serialize_prediction(pred: Any) -> Dict[str, Any]:
    return {
        "model_name": pred.model_name,
        "model_version": pred.model_version,
        "prediction": pred.prediction,
        "confidence": pred.confidence,
        "reasoning": pred.reasoning,
        "context": pred.context if isinstance(pred.context, dict) else {},
        "computation_time_ms": pred.computation_time_ms,
        "health_status": pred.health_status,
    }


async def evaluate_transformer_prediction(
    *,
    symbol: str,
    context: Dict[str, Any],
    model_registry: MCPModelRegistry,
    delta_client: Any,
    t0: float,
    serialize_prediction: Any,
) -> Dict[str, Any]:
    """Run transformer inference and map to a trading decision."""
    import time

    import pandas as pd

    from agent.core.portfolio_intelligence import (
        apply_portfolio_guard_to_verdict,
        evaluate_portfolio_guard,
        fetch_portfolio_exposure_snapshot,
    )

    if not delta_client:
        raise RuntimeError("delta_client not set; cannot fetch market frames")

    df5, df15, df1h, df_fund, df_oi, df_mark = await fetch_v43_market_frames(
        delta_client, symbol
    )
    if df5.empty or len(df5) < 2:
        raise ValueError("Insufficient OHLCV data for transformer prediction")

    from agent.core.v43_contract_state import get_contract_state

    ticker_row: Dict[str, Any] = {}
    if isinstance(df_oi, pd.DataFrame) and not df_oi.empty:
        ticker_row = df_oi.iloc[-1].to_dict()
    contract_state = await get_contract_state(symbol, ticker_row=ticker_row)

    req_id = f"pred_tf_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    mctx: Dict[str, Any] = {
        **(context or {}),
        "v43_df5m": df5,
        "v43_df15m": df15,
        "v43_df1h": df1h,
        "v43_df_funding": df_fund,
        "v43_df_oi": df_oi,
        "v43_df_mark": df_mark,
        "v43_contract_state": contract_state,
        "symbol": symbol,
    }
    if not contract_state.is_operational:
        mctx["market_health_hold"] = True
        mctx["market_health_reason"] = (
            f"contract_state={contract_state.state} "
            f"trading_status={contract_state.trading_status}"
        )

    model_request = MCPModelRequest(
        request_id=req_id,
        features=[],
        context=mctx,
        require_explanation=False,
    )
    model_response = await model_registry.get_predictions(model_request)
    pred0 = model_response.predictions[0]
    pctx = pred0.context if isinstance(pred0.context, dict) else {}

    continuous = pctx.get("transformer_continuous_preds") or {}
    future_return = float(
        continuous.get("future_return_scalp_10m")
        or continuous.get("future_return")
        or pctx.get("expected_return", 0.0)
        or 0.0
    )
    vol_regime = str(pctx.get("transformer_vol_regime") or "NORMAL")
    regime = str(pctx.get("regime") or "neutral")
    confidence = float(pred0.confidence or pctx.get("entry_confidence", 0.0) or 0.0)

    bundle_metadata: Dict[str, Any] = {}
    node = model_registry.get_model(pred0.model_name)
    if node is not None and hasattr(node, "_bundle_metadata"):
        raw_meta = getattr(node, "_bundle_metadata")
        if isinstance(raw_meta, dict):
            bundle_metadata = raw_meta

    threshold = _resolve_threshold(bundle_metadata)
    signal, confidence, reason_codes = map_prediction_to_signal(
        future_return=future_return,
        threshold=threshold,
        vol_regime=vol_regime,
        confidence=confidence,
        strong_edge_multiplier=float(
            getattr(settings, "transformer_strong_edge_multiplier", 1.5) or 1.5
        ),
        extreme_regime_veto=bool(
            getattr(settings, "transformer_extreme_regime_veto", True)
        ),
        min_confidence=float(getattr(settings, "transformer_min_confidence", 0.55) or 0.55),
    )

    if mctx.get("market_health_hold"):
        signal = "HOLD"
        confidence = 0.0
        reason_codes = list(reason_codes) + ["market_health_hold"]

    position_size = _default_position_size(confidence) if signal in _ENTRY_SIGNALS else 0.0
    bar_idx = closed_5m_bar_index(df5)

    model_predictions_payload: List[Dict[str, Any]] = [
        serialize_prediction(p) for p in model_response.predictions
    ]

    market_context: Dict[str, Any] = {
        **mctx,
        "format": "jacksparrow_transformer_btcusd_15m",
        "expected_return": future_return,
        "threshold": threshold,
        "regime": regime,
        "transformer_vol_regime": vol_regime,
        "transformer_signal": signal,
        "transformer_reason_codes": reason_codes,
        "closed_bar_index": bar_idx,
        "model_predictions": model_predictions_payload,
    }

    policy_verdict = PolicyVerdict(
        signal=signal,
        confidence=confidence,
        position_size=position_size,
        reason_codes=reason_codes,
        ml_evidence_id=None,
        adopted_ml_candidate=signal in _ENTRY_SIGNALS,
    )

    portfolio_snap = await fetch_portfolio_exposure_snapshot(symbol, market_context)
    market_context["portfolio_exposure"] = portfolio_snap.to_dict()
    portfolio_guard = evaluate_portfolio_guard(
        portfolio_snap,
        symbol=symbol,
        proposed_signal=policy_verdict.signal,
        proposed_size_fraction=float(policy_verdict.position_size or 0.0),
    )
    policy_verdict = apply_portfolio_guard_to_verdict(
        policy_verdict,
        portfolio_guard,
        symbol=symbol,
    )
    market_context["portfolio_guard"] = portfolio_guard.to_dict()

    signal = policy_verdict.signal
    confidence = float(policy_verdict.confidence or 0.0)
    position_size = float(policy_verdict.position_size or 0.0)

    reasoning_chain = _build_reasoning_chain(
        symbol=symbol,
        signal=signal,
        confidence=confidence,
        future_return=future_return,
        threshold=threshold,
        vol_regime=vol_regime,
        regime=regime,
        model_predictions=model_predictions_payload,
        market_context=market_context,
        reason_codes=list(policy_verdict.reason_codes or reason_codes),
    )

    closed_feats = pctx.get("closed_bar_features") or {}
    ts = datetime.now(timezone.utc)
    feat_list = [
        MCPFeature(
            name=str(k),
            version="1.0.0",
            value=float(v),
            timestamp=ts,
            quality=FeatureQuality.HIGH,
            metadata={"transformer": True},
            computation_time_ms=0.0,
        )
        for k, v in sorted(closed_feats.items())
        if isinstance(v, (int, float))
    ][:80]
    if not feat_list:
        feat_list = [
            MCPFeature(
                name="transformer_placeholder",
                version="1.0.0",
                value=0.0,
                timestamp=ts,
                quality=FeatureQuality.MEDIUM,
                metadata={},
                computation_time_ms=0.0,
            )
        ]

    feature_response = MCPFeatureResponse(
        features=feat_list,
        quality_score=0.9,
        overall_quality=FeatureQuality.HIGH,
        timestamp=ts,
        request_id=req_id,
    )

    result: Dict[str, Any] = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc),
        "features": {
            "data": [
                {"name": f.name, "value": f.value, "quality": f.quality.value}
                for f in feature_response.features
            ],
            "quality_score": feature_response.quality_score,
            "overall_quality": feature_response.overall_quality.value,
            "count": len(feature_response.features),
        },
        "models": {
            "predictions": model_predictions_payload,
            "consensus_prediction": model_response.consensus_prediction,
            "consensus_confidence": model_response.consensus_confidence,
            "healthy_models": model_response.healthy_models,
            "total_models": model_response.total_models,
        },
        "model_predictions": model_predictions_payload,
        "market_context": market_context,
        "reasoning": reasoning_chain,
        "decision": {
            "signal": signal,
            "position_size": position_size,
            "confidence": confidence,
            "reasoning": reasoning_chain.get("conclusion"),
            "policy_reason_codes": list(policy_verdict.reason_codes or []),
        },
        "policy_verdict": policy_verdict.model_dump(mode="json"),
    }
    result["inference_latency_ms"] = (time.perf_counter() - t0) * 1000.0

    logger.info(
        "transformer_decision_complete",
        symbol=symbol,
        signal=signal,
        confidence=confidence,
        future_return=future_return,
        threshold=threshold,
        vol_regime=vol_regime,
        reason_codes=list(policy_verdict.reason_codes or []),
    )
    return result


async def safe_evaluate_transformer_prediction(
    *,
    symbol: str,
    context: Dict[str, Any],
    model_registry: Optional[MCPModelRegistry],
    delta_client: Any,
    t0: float,
    serialize_prediction: Any,
    error_response_factory: Any,
) -> Dict[str, Any]:
    """Wrapper that returns orchestrator error responses on failure."""
    if not model_registry or not model_registry.models:
        return error_response_factory(
            symbol=symbol,
            context=context,
            error_code="NO_MODELS_REGISTERED",
            error_message="No transformer model registered.",
        )
    try:
        return await evaluate_transformer_prediction(
            symbol=symbol,
            context=context,
            model_registry=model_registry,
            delta_client=delta_client,
            t0=t0,
            serialize_prediction=serialize_prediction,
        )
    except (NoModelsRegisteredError, NoHealthyModelPredictionsError) as exc:
        return error_response_factory(
            symbol=symbol,
            context=context,
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
    except Exception as exc:
        logger.error(
            "transformer_decision_failed",
            symbol=symbol,
            error=str(exc),
            exc_info=True,
        )
        return error_response_factory(
            symbol=symbol,
            context=context or {},
            error_code=type(exc).__name__,
            error_message=str(exc),
        )
