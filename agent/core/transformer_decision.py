"""Slim transformer-only decision path for MCP orchestrator (agent synthesis)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.market_frames import closed_5m_bar_index, fetch_mtf_market_frames
from agent.core.market_understanding import (
    build_views_from_predictions,
    resolution_to_tf_key,
    synthesize_agent_decision,
)
from agent.core.path_execution_plan import build_execution_plan
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
_DECISION_PATH = "transformer_agent_synthesis"


def _view_to_multi_tf_dict(view: Any) -> Dict[str, Any]:
    """UI-compatible multi_tf entry derived from TfMarketView."""
    direction = "neutral"
    local_signal = "HOLD"
    if view.setup_stance == "long_path" or view.climate_stance == "long":
        direction = "bullish"
        local_signal = "BUY"
    elif view.setup_stance == "short_path" or view.climate_stance == "short":
        direction = "bearish"
        local_signal = "SELL"
    elif view.timing_stance == "with":
        direction = "bullish" if view.path_imbalance_z > 0 else "bearish"
    return {
        "tf_key": view.tf_key,
        "resolution": view.resolution,
        "local_signal": local_signal,
        "direction": direction,
        "path_edge": view.path_edge,
        "long_edge": view.long_edge,
        "short_edge": view.short_edge,
        "winning_edge": max(view.long_edge, view.short_edge),
        "size_scale": 1.0,
        "threshold": view.typical_abs_edge,
        "vol_regime": view.vol_regime,
        "regime": view.climate_stance or view.setup_stance or view.timing_stance or "neutral",
        "confidence": view.confidence,
        "quality": view.quality,
        "risk": view.risk,
        "mfe": view.mfe,
        "mae": view.mae,
        "drawdown_before_mfe": getattr(view, "drawdown_before_mfe", 0.0),
        "future_oi_change_pct": getattr(view, "future_oi_change_pct", 0.0),
        "imbalance_ratio": getattr(view, "imbalance_ratio", 0.0),
        "trend_strength": view.trend_strength,
        "path_imbalance_z": view.path_imbalance_z,
        "reason_codes": [],
        "model_name": view.model_name,
        "climate_stance": view.climate_stance,
        "setup_stance": view.setup_stance,
        "timing_stance": view.timing_stance,
    }


def _per_tf_log_summary(views: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key in ("tf_2h", "tf_1h", "tf_30m", "tf_15m", "tf_5m"):
        view = views.get(key)
        if view is None:
            continue
        rows.append(
            {
                "tf": key,
                "mfe": round(float(view.mfe), 6),
                "mae": round(float(view.mae), 6),
                "path_imbalance_z": round(float(view.path_imbalance_z), 4),
                "vol_regime": view.vol_regime,
                "trend_strength": round(float(view.trend_strength), 4),
                "drawdown_before_mfe": round(float(view.drawdown_before_mfe), 6),
                "climate": view.climate_stance,
                "setup": view.setup_stance,
                "timing": view.timing_stance,
            }
        )
    return rows


def _default_position_size(confidence: float, size_fraction: float | None = None) -> float:
    if size_fraction is not None and size_fraction > 0:
        return float(max(0.01, min(1.0, size_fraction)))
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
    climate: str = "",
    setup: str = "",
    timing: str = "",
    thesis: str = "",
) -> Dict[str, Any]:
    chain_id = str(uuid.uuid4())
    conclusion = (
        f"Agent synthesis: {signal} "
        f"(climate={climate or regime}, setup={setup}, timing={timing}, "
        f"thesis={thesis}, path_edge={path_edge:.5f}, thr={threshold:.5f}, "
        f"vol_regime={vol_regime})"
    )
    return {
        "chain_id": chain_id,
        "conclusion": conclusion,
        "final_confidence": float(confidence),
        "signal_strength": signal if signal in _ENTRY_SIGNALS else "HOLD",
        "steps": [
            {
                "step_number": 1,
                "step_name": "agent_market_synthesis",
                "description": conclusion,
                "evidence": [
                    f"symbol={symbol}",
                    f"climate={climate}",
                    f"setup={setup}",
                    f"timing={timing}",
                    f"thesis={thesis}",
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


async def evaluate_transformer_prediction(
    *,
    symbol: str,
    context: Dict[str, Any],
    model_registry: MCPModelRegistry,
    delta_client: Any,
    t0: float,
    serialize_prediction: Any,
) -> Dict[str, Any]:
    """Run per-TF transformer inference and climate/setup/timing synthesis."""
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

    decision_path = _DECISION_PATH
    per_tf_contexts: Dict[str, Dict[str, Any]] = {}
    multi_tf_predictions: Dict[str, Any] = {}

    views = build_views_from_predictions(
        predictions=model_response.predictions,
        model_registry=model_registry,
        resolution_to_tf_key_fn=resolution_to_tf_key,
    )
    for tf_key, view in views.items():
        per_tf_contexts[tf_key] = next(
            (
                (p.context if isinstance(p.context, dict) else {})
                for p in model_response.predictions
                if str(getattr(p, "model_name", "")) == view.model_name
                or (
                    isinstance(getattr(p, "context", None), dict)
                    and p.context.get("tf_key") == tf_key
                )
            ),
            {},
        )
        multi_tf_predictions[tf_key] = _view_to_multi_tf_dict(view)

    state = synthesize_agent_decision(views)
    market_state_payload = state.to_dict()
    signal = str(state.wire_signal)
    confidence = float(state.confidence)
    reason_codes = list(state.reason_codes)
    path_edge = float(state.path_edge)
    threshold = float(state.threshold)
    regime = str(state.climate)
    vol_regime = str(state.vol_regime or "NORMAL")
    policy_size_scale = float(state.size_scale or 0.0)
    policy_long_edge = float(state.long_edge)
    policy_short_edge = float(state.short_edge)
    policy_winning_edge = float(state.winning_edge or abs(path_edge))
    policy_mfe = float(state.mfe)
    policy_mae = float(state.mae)
    policy_future_vol = float(state.future_volatility)
    policy_primary_tf = str(state.primary_tf or "tf_15m")
    cross_tf_summary = {
        "climate": state.climate,
        "setup": state.setup,
        "timing": state.timing,
        "thesis": state.thesis,
        "dominant_tf": policy_primary_tf,
        "primary_execution_tf": policy_primary_tf,
        "decision_path": decision_path,
    }
    tf_summary = _per_tf_log_summary(views)
    logger.info(
        "transformer_agent_synthesis_complete",
        symbol=symbol,
        thesis=state.thesis,
        wire_signal=signal,
        climate=state.climate,
        setup=state.setup,
        timing=state.timing,
        path_edge=path_edge,
        threshold=threshold,
        reason_codes=reason_codes,
        per_tf=tf_summary,
    )

    if mctx.get("market_health_hold"):
        signal = "HOLD"
        confidence = 0.0
        reason_codes = list(reason_codes) + ["market_health_hold"]

    execution_plan: Dict[str, Any] = {}
    if signal in _ENTRY_SIGNALS:
        execution_plan = build_execution_plan(
            signal=signal,
            confidence=confidence,
            size_scale=float(policy_size_scale or 1.0),
            long_edge=float(policy_long_edge),
            short_edge=float(policy_short_edge),
            winning_edge=float(policy_winning_edge or abs(path_edge)),
            threshold=threshold,
            primary_tf=str(policy_primary_tf or ""),
            mfe=float(policy_mfe),
            mae=float(policy_mae),
            future_volatility=float(policy_future_vol),
            vol_regime=vol_regime,
            reason_codes=reason_codes,
            entry_portfolio_margin_fraction=float(
                getattr(settings, "entry_portfolio_margin_fraction", 0.6) or 0.6
            ),
            size_floor=float(getattr(settings, "transformer_size_floor", 0.35) or 0.35),
            edge_weight=float(
                getattr(settings, "transformer_size_edge_weight", 1.0) or 1.0
            ),
            sl_adverse_mult=float(getattr(settings, "path_sl_adverse_mult", 1.0) or 1.0),
            tp_favorable_mult=float(
                getattr(settings, "path_tp_favorable_mult", 1.0) or 1.0
            ),
            min_risk_reward_ratio=float(
                getattr(settings, "min_risk_reward_ratio", 1.2) or 1.2
            ),
            rr_size_factor=float(getattr(settings, "path_rr_size_factor", 0.7) or 0.7),
        )
        signal = str(execution_plan.get("signal") or signal)
        reason_codes = list(execution_plan.get("reason_codes") or reason_codes)
        position_size = _default_position_size(
            confidence,
            float(execution_plan.get("size_fraction") or 0.0),
        )
    else:
        position_size = 0.0

    bar_idx = closed_5m_bar_index(df5)

    model_predictions_payload: List[Dict[str, Any]] = [
        serialize_prediction(p) for p in model_response.predictions
    ]

    mtf_context = build_mtf_aggregation_context(
        per_tf_contexts=per_tf_contexts,
        policy_result={
            "signal": signal,
            "reason_codes": reason_codes,
            "cross_tf_summary": cross_tf_summary,
        },
    )

    transformer_features: Dict[str, float] = {}
    primary_key = str(policy_primary_tf or "tf_15m")
    primary_ctx = per_tf_contexts.get(primary_key) or {}
    for k, v in (primary_ctx.get("closed_bar_features") or {}).items():
        if isinstance(v, (int, float)):
            transformer_features[str(k)] = float(v)

    market_context: Dict[str, Any] = {
        **mctx,
        **mtf_context,
        "format": "jacksparrow_transformer_btcusd_mtf",
        "path_edge": path_edge,
        "long_edge": float(policy_long_edge),
        "short_edge": float(policy_short_edge),
        "threshold": threshold,
        "regime": regime,
        "transformer_vol_regime": vol_regime,
        "transformer_signal": signal,
        "transformer_reason_codes": reason_codes,
        "multi_tf_predictions": multi_tf_predictions,
        "cross_tf_summary": cross_tf_summary,
        "closed_bar_index": bar_idx,
        "model_predictions": model_predictions_payload,
        "execution_plan": execution_plan,
        "transformer_features": transformer_features,
        "decision_path": decision_path,
        "market_state": market_state_payload,
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
        climate=state.climate,
        setup=state.setup,
        timing=state.timing,
        thesis=state.thesis,
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
            metadata={"transformer": True, "synthesis": True},
            computation_time_ms=0.0,
        )
        for k, v in sorted(closed_feats.items())
        if isinstance(v, (int, float))
    ][:80]
    if not feat_list:
        feat_list = [
            MCPFeature(
                name="transformer_synthesis_placeholder",
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
        climate=state.climate,
        setup=state.setup,
        timing=state.timing,
        thesis=state.thesis,
        reason_codes=list(policy_verdict.reason_codes or []),
        tf_count=len(multi_tf_predictions),
        per_tf=tf_summary,
        decision_path=decision_path,
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
