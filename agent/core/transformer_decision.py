"""Slim transformer-only decision path for MCP orchestrator (per-TF ensemble)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.mtf_decision_policy import (
    evaluate_mtf_policy,
    interpret_tf_prediction,
    resolution_to_tf_key,
)
from agent.core.market_frames import closed_5m_bar_index, fetch_mtf_market_frames
from agent.data.feature_server import FeatureQuality, MCPFeature, MCPFeatureResponse
from agent.events.schemas import PolicyVerdict
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelRequest,
    NoHealthyModelPredictionsError,
    NoModelsRegisteredError,
)
from agent.models.transformer_context_builder import build_mtf_aggregation_context

logger = structlog.get_logger()

_ENTRY_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})


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
    path_edge: float,
    threshold: float,
    vol_regime: str,
    regime: str,
    model_predictions: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    reason_codes: List[str],
) -> Dict[str, Any]:
    chain_id = str(uuid.uuid4())
    conclusion = (
        f"MTF Transformer: {signal} "
        f"(path_edge={path_edge:.5f}, thr={threshold:.5f}, "
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
                "step_name": "mtf_transformer_inference",
                "description": conclusion,
                "evidence": [
                    f"symbol={symbol}",
                    f"path_edge={path_edge:.5f}",
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


def _stance_to_dict(stance: Any) -> Dict[str, Any]:
    return {
        "tf_key": stance.tf_key,
        "resolution": stance.resolution,
        "local_signal": stance.local_signal,
        "direction": stance.direction,
        "path_edge": stance.path_edge,
        "threshold": stance.threshold,
        "vol_regime": stance.vol_regime,
        "regime": stance.regime,
        "confidence": stance.confidence,
        "quality": stance.quality,
        "risk": stance.risk,
        "reason_codes": list(stance.reason_codes),
        "model_name": stance.model_name,
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
    """Run per-TF transformer inference and apply MTF decision policy."""
    import time

    import pandas as pd

    from agent.core.portfolio_intelligence import (
        apply_portfolio_guard_to_verdict,
        evaluate_portfolio_guard,
        fetch_portfolio_exposure_snapshot,
    )

    if not delta_client:
        raise RuntimeError("delta_client not set; cannot fetch market frames")

    df5, df15, df30, df1h, df2h, df_fund, df_oi, df_mark = await fetch_mtf_market_frames(
        delta_client, symbol
    )
    if df5.empty or len(df5) < 2:
        raise ValueError("Insufficient OHLCV data for transformer prediction")

    from agent.core.contract_state import get_contract_state

    ticker_row: Dict[str, Any] = {}
    if isinstance(df_oi, pd.DataFrame) and not df_oi.empty:
        ticker_row = df_oi.iloc[-1].to_dict()
    contract_state = await get_contract_state(symbol, ticker_row=ticker_row)

    req_id = f"pred_tf_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    mctx: Dict[str, Any] = {
        **(context or {}),
        "v43_df5m": df5,
        "v43_df15m": df15,
        "v43_df30m": df30,
        "v43_df1h": df1h,
        "v43_df2h": df2h,
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

    stances: Dict[str, Any] = {}
    per_tf_contexts: Dict[str, Dict[str, Any]] = {}
    for pred in model_response.predictions:
        pctx = pred.context if isinstance(pred.context, dict) else {}
        tf_key = str(pctx.get("tf_key") or "")
        if not tf_key:
            node = model_registry.get_model(pred.model_name)
            if node is not None and hasattr(node, "resolution"):
                tf_key = resolution_to_tf_key(getattr(node, "resolution"))
            else:
                tf_key = f"tf_unknown_{pred.model_name}"
        bundle_metadata: Dict[str, Any] = {}
        node = model_registry.get_model(pred.model_name)
        if node is not None and hasattr(node, "_bundle_metadata"):
            raw_meta = getattr(node, "_bundle_metadata")
            if isinstance(raw_meta, dict):
                bundle_metadata = raw_meta
        stance = interpret_tf_prediction(
            tf_key=tf_key,
            prediction_context=pctx,
            bundle_metadata=bundle_metadata,
            model_name=pred.model_name,
        )
        stances[tf_key] = stance
        per_tf_contexts[tf_key] = pctx

    policy = evaluate_mtf_policy(stances)

    signal = policy.signal
    confidence = float(policy.confidence)
    reason_codes = list(policy.reason_codes)
    path_edge = float(policy.primary_path_edge)
    threshold = float(policy.primary_threshold)
    regime = str(policy.primary_regime)
    vol_regime = "NORMAL"
    for stance in stances.values():
        if stance.tf_key in ("tf_15m", "tf_30m"):
            vol_regime = stance.vol_regime
            break

    if mctx.get("market_health_hold"):
        signal = "HOLD"
        confidence = 0.0
        reason_codes = list(reason_codes) + ["market_health_hold"]

    position_size = _default_position_size(confidence) if signal in _ENTRY_SIGNALS else 0.0
    bar_idx = closed_5m_bar_index(df5)

    model_predictions_payload: List[Dict[str, Any]] = [
        serialize_prediction(p) for p in model_response.predictions
    ]

    mtf_context = build_mtf_aggregation_context(
        per_tf_contexts=per_tf_contexts,
        policy_result={
            "signal": signal,
            "reason_codes": reason_codes,
            "cross_tf_summary": policy.cross_tf_summary,
        },
    )

    market_context: Dict[str, Any] = {
        **mctx,
        **mtf_context,
        "format": "jacksparrow_transformer_btcusd_mtf",
        "path_edge": path_edge,
        "threshold": threshold,
        "regime": regime,
        "transformer_vol_regime": vol_regime,
        "transformer_signal": signal,
        "transformer_reason_codes": reason_codes,
        "multi_tf_predictions": {
            k: _stance_to_dict(v) for k, v in policy.multi_tf_stances.items()
        },
        "cross_tf_summary": policy.cross_tf_summary,
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
        path_edge=path_edge,
        threshold=threshold,
        vol_regime=vol_regime,
        regime=regime,
        model_predictions=model_predictions_payload,
        market_context=market_context,
        reason_codes=list(policy_verdict.reason_codes or reason_codes),
    )

    closed_feats: Dict[str, float] = {}
    for pctx in per_tf_contexts.values():
        for k, v in (pctx.get("closed_bar_features") or {}).items():
            if isinstance(v, (int, float)):
                closed_feats[f"{pctx.get('resolution', 'tf')}_{k}"] = float(v)

    ts = datetime.now(timezone.utc)
    feat_list = [
        MCPFeature(
            name=str(k),
            version="1.0.0",
            value=float(v),
            timestamp=ts,
            quality=FeatureQuality.HIGH,
            metadata={"transformer": True, "mtf": True},
            computation_time_ms=0.0,
        )
        for k, v in sorted(closed_feats.items())
        if isinstance(v, (int, float))
    ][:80]
    if not feat_list:
        feat_list = [
            MCPFeature(
                name="transformer_mtf_placeholder",
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
        path_edge=path_edge,
        threshold=threshold,
        vol_regime=vol_regime,
        reason_codes=list(policy_verdict.reason_codes or []),
        tf_count=len(stances),
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
