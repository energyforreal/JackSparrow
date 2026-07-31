"""
MCP Orchestrator - Core coordinator for all MCP components.

Coordinates the interaction between MCP Feature Server, MCP Model Registry,
and MCP Reasoning Engine to provide unified AI agent functionality.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import asyncio
import time
import uuid
import structlog

from agent.data.feature_server import (
    MCPFeature,
    MCPFeatureRequest,
    MCPFeatureResponse,
    MCPFeatureServer,
    FeatureQuality,
)
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelRequest,
    MCPModelResponse,
    NoModelsRegisteredError,
    NoHealthyModelPredictionsError,
)
from agent.memory.vector_store import VectorMemoryStore, DecisionContext
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    ModelPredictionRequestEvent,
    ModelPredictionCompleteEvent,
    DecisionReadyEvent,
    EventType,
    PolicyAuthority,
    PolicyVerdict,
)
from agent.core.config import settings
from agent.core.agent_introspection import build_introspection_snapshot
from agent.core.log_context import (
    EVENT_MODEL_PREDICTION,
    KEY_FEATURE_QUALITY,
    KEY_SYMBOL,
)
from feature_store.feature_registry import get_feature_list

logger = structlog.get_logger()

_last_position_reconcile_ts: float = 0.0
_POSITION_RECONCILE_STALE_SECONDS: float = 30.0


def mark_position_reconcile_completed() -> None:
    """Update reconcile freshness timestamp (called after background reconcile)."""
    global _last_position_reconcile_ts
    _last_position_reconcile_ts = time.time()


async def _exchange_has_open_position_async(symbol: str) -> bool:
    """True when agent memory or Delta testnet reports an open position for symbol."""
    global _last_position_reconcile_ts
    sym = str(symbol or "").strip().upper()
    if not sym:
        return False

    now_mono = time.time()
    if (now_mono - _last_position_reconcile_ts) > _POSITION_RECONCILE_STALE_SECONDS:
        try:
            from agent.core.execution import execution_module
            from agent.core.position_reconcile import reconcile_positions_with_exchange

            await asyncio.wait_for(
                reconcile_positions_with_exchange(execution_module),
                timeout=5.0,
            )
            _last_position_reconcile_ts = time.time()
        except Exception as exc:
            logger.warning(
                "position_reconcile_before_entry_failed",
                symbol=sym,
                error=str(exc),
                exc_info=True,
            )
            try:
                from agent.events.schemas import RiskAlertEvent

                alert = RiskAlertEvent(
                    source="mcp_orchestrator",
                    payload={
                        "alert_type": "reconciliation_failed",
                        "symbol": sym,
                        "message": "Exchange reconciliation failed; blocking new entry",
                        "error": str(exc),
                    },
                )
                await event_bus.publish(alert)
            except Exception:
                pass
            return True

    try:
        from agent.core.execution import execution_module

        local_pos = execution_module.position_manager.get_position(sym)
        if local_pos and str(local_pos.get("status") or "").lower() == "open":
            return True

        view = await execution_module.get_margined_positions_view()
        rows = view.get("result") if isinstance(view, dict) else None
        if not isinstance(rows, list):
            return False
        for row in rows:
            if not isinstance(row, dict):
                continue
            ps = str(row.get("product_symbol") or row.get("symbol") or "").upper()
            if ps != sym:
                continue
            try:
                if abs(float(row.get("size") or 0)) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    except Exception:
        return False
    return False


def _v43_reasoning_portfolio_risk_overlay(symbol: str) -> Dict[str, Any]:
    """Fields expected by reasoning step 4 (risk) from live AgentState."""
    try:
        from agent.core.context_manager import context_manager, AgentState as _AgentState

        st = context_manager.get_state()
    except Exception:
        return {}
    if st is None:
        logger.warning(
            "v43_reasoning_portfolio_fallback",
            symbol=symbol,
            message="context_manager state unavailable; using synthetic initial_balance overlay",
        )
        try:
            st = _AgentState()
            init_bal = float(getattr(settings, "initial_balance", 10000.0) or 10000.0)
            st.portfolio_value = init_bal
            st.cash_balance = init_bal
        except Exception:
            return {}
    try:
        pv = float(st.portfolio_value)
        cash = float(st.cash_balance)
    except (TypeError, ValueError):
        return {}
    overlay: Dict[str, Any] = {
        "portfolio_value": pv,
        "available_balance": cash,
        "sharpe_ratio_rolling": float(getattr(st, "sharpe_ratio", 0.0) or 0.0),
        "max_drawdown_current": float(getattr(st, "max_drawdown", 0.0) or 0.0),
    }
    try:
        rl = st.risk_limits if isinstance(st.risk_limits, dict) else {}
        lim = max(1, int(rl.get("max_open_positions", 5) or 5))
        npos = len(getattr(st, "positions", None) or {})
        overlay["portfolio_heat"] = float(npos) / float(lim)
    except Exception:
        pass
    try:
        positions = getattr(st, "positions", None) or {}
        if symbol and symbol in positions:
            overlay["has_open_position"] = True
    except Exception:
        pass
    return overlay


def _merge_prediction_context_with_agent_state(
    symbol: str, context: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Caller context wins on key clashes; agent state fills portfolio / risk gaps."""
    out = dict(context or {})
    for k, v in _v43_reasoning_portfolio_risk_overlay(symbol).items():
        if k not in out:
            out[k] = v
    return out


def _enrich_confidence_semantics(payload: Dict[str, Any]) -> None:
    """Split policy vs calibrated display confidence for dashboard consumers."""
    reasoning_chain = payload.get("reasoning_chain")
    policy_conf = float(payload.get("confidence") or 0.0)
    chain_final: Optional[float] = None
    if isinstance(reasoning_chain, dict):
        fc = reasoning_chain.get("final_confidence")
        if fc is not None:
            try:
                chain_final = float(fc)
            except (TypeError, ValueError):
                chain_final = None
    display_conf = chain_final if chain_final is not None else policy_conf
    signal = str(payload.get("signal") or "HOLD").upper()
    actionable = signal in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL")
    payload["policy_confidence"] = policy_conf
    payload["display_confidence"] = display_conf
    payload["is_actionable_entry"] = actionable
    if chain_final is not None:
        payload["calibrated_confidence"] = chain_final
    payload["raw_confidence"] = policy_conf
    if isinstance(reasoning_chain, dict):
        ss = reasoning_chain.get("signal_strength")
        if ss is not None:
            try:
                payload["signal_strength"] = float(ss)
            except (TypeError, ValueError):
                pass


def _decision_ws_metadata(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extra fields on DecisionReadyEvent.payload for dashboard WebSocket consumers."""
    if not result or not isinstance(result, dict):
        return {}
    out: Dict[str, Any] = {}
    lat = result.get("inference_latency_ms")
    if lat is not None:
        try:
            out["inference_latency_ms"] = float(lat)
        except (TypeError, ValueError):
            pass
    out["inference_source"] = "agent"
    out["inference_mode"] = "primary"
    mp = result.get("model_predictions") or []
    if isinstance(mp, list) and mp and isinstance(mp[0], dict):
        mv = mp[0].get("model_version")
        if mv:
            out["model_version"] = str(mv)
    return out


class MCPOrchestrator:
    """Main MCP Orchestrator coordinating all MCP components."""
    
    def __init__(self):
        """Initialize MCP Orchestrator."""
        self.feature_server: Optional[MCPFeatureServer] = None
        self.model_registry: Optional[MCPModelRegistry] = None
        self.vector_store: Optional[VectorMemoryStore] = None
        self._required_feature_names_cache: List[str] = []
        self.delta_client = None
        self._initialized = False
        self._last_entry_decision_bar: Optional[int] = None
    
    async def initialize(self):
        """Initialize all MCP components."""
        try:
            logger.info("mcp_orchestrator_initializing", message="Starting MCP Orchestrator initialization")

            # Initialize MCP Feature Server
            self.feature_server = MCPFeatureServer()
            await self.feature_server.initialize()
            logger.info("mcp_orchestrator_feature_server_initialized")

            # Initialize MCP Model Registry
            self.model_registry = MCPModelRegistry()
            await self.model_registry.initialize()

            # Discover and load models
            from agent.models.model_discovery import ModelDiscovery
            discovery = ModelDiscovery(self.model_registry)
            discovered_models = await discovery.discover_models()
            logger.info("mcp_orchestrator_models_discovered",
                       model_count=len(discovered_models),
                       registry_models=len(self.model_registry.models))
            loaded_n = len(self.model_registry.models)
            if loaded_n == 1:
                logger.warning(
                    "mcp_orchestrator_single_model_loaded",
                    model_count=loaded_n,
                    policy_mode=str(
                        getattr(settings, "agent_policy_mode", "ml_only") or "ml_only"
                    ),
                    message=(
                        "Only one ML model is active; fusion/adjudication may emit "
                        "HOLD more often until additional models load."
                    ),
                )
            self._required_feature_names_cache = (
                self.model_registry.get_required_feature_names()
                if self.model_registry
                else []
            )
            logger.info(
                "mcp_orchestrator_required_features_cached",
                feature_count=len(self._required_feature_names_cache),
                source="model_registry" if self._required_feature_names_cache else "fallback_pending",
            )

            # Enforce that at least one ML model is available before continuing
            # when strict mode is enabled. In non-strict (best-effort) mode the agent will
            # continue in monitoring mode without ML predictions.
            # Default to best-effort (False) so monitoring deployments can start without
            # a bundle and warm up when artifacts appear.
            require_models = bool(getattr(settings, "require_models_on_startup", False))
            if self.model_registry:
                try:
                    reg_health = await asyncio.wait_for(
                        self.model_registry.get_health_status(),
                        timeout=5.0,
                    )
                except Exception:
                    reg_health = {}
                logger.info(
                    "mcp_orchestrator_startup_model_registry_check",
                    service="agent",
                    component="model_registry",
                    model_dir=str(getattr(settings, "model_dir", "")),
                    total_models=reg_health.get("total_models", len(self.model_registry.models)),
                    healthy_models=reg_health.get("healthy_models", 0),
                    registry_health=reg_health.get("registry_health"),
                    discovered_metadata_files=len(discovered_models),
                )
            if not self.model_registry.models:
                if require_models:
                    logger.critical(
                        "mcp_orchestrator_no_models_loaded",
                        discovered_count=len(discovered_models),
                        discovery_mode="rule_based_ic",
                        message=(
                            "No intelligence models loaded during initialization with "
                            "require_models_on_startup=True (IC bundle)."
                        ),
                    )
                    raise RuntimeError(
                        "MCP Orchestrator initialization failed: no IC model loaded."
                    )
                else:
                    logger.warning(
                        "mcp_orchestrator_no_models_loaded_monitoring_mode",
                        discovered_count=len(discovered_models),
                        discovery_mode="rule_based_ic",
                        message=(
                            "No IC model loaded during initialization and "
                            "require_models_on_startup=False. "
                            "Agent will continue in monitoring mode until MODEL_DIR bundle is valid."
                        ),
                    )

            logger.info("mcp_orchestrator_model_registry_initialized")

            from agent.memory.vector_store_factory import create_vector_store

            self.vector_store = await create_vector_store()

            event_bus.subscribe(EventType.MODEL_PREDICTION_REQUEST, self._handle_prediction_request)

            self._initialized = True
            logger.info("mcp_orchestrator_initialization_complete",
                       message="MCP Orchestrator fully initialized and ready")

        except Exception as e:
            logger.error("mcp_orchestrator_initialization_failed",
                        error=str(e),
                        exc_info=True)
            raise
    
    async def shutdown(self):
        """Shutdown all MCP components."""
        try:
            logger.info("mcp_orchestrator_shutdown_starting")

            if self.vector_store:
                await self.vector_store.shutdown()
                self.vector_store = None

            if self.model_registry:
                await self.model_registry.shutdown()

            if self.feature_server:
                await self.feature_server.shutdown()

            logger.info("mcp_orchestrator_shutdown_complete")

        except Exception as e:
            logger.error("mcp_orchestrator_shutdown_failed", error=str(e), exc_info=True)

    async def validate_models_dry_run(self) -> bool:
        """Run a minimal inference pass to verify the v43 bundle loads correctly."""
        import math

        if not self.model_registry or not self.model_registry.models:
            return False
        try:
            from agent.models.mcp_model_node import MCPModelRequest

            names = self._required_feature_names_cache or get_feature_list()
            feats = [0.0] * max(1, len(names))
            req = MCPModelRequest(
                request_id="dry_run_validation",
                features=feats,
                context={"dry_run": True, "symbol": getattr(settings, "trading_symbol", "BTCUSD")},
            )
            resp = await self.model_registry.get_predictions(req)
            preds = getattr(resp, "predictions", None) or []
            if not preds:
                return False
            p0 = preds[0]
            ctx = getattr(p0, "context", None) or {}
            er = ctx.get("expected_return") if isinstance(ctx, dict) else None
            if er is None:
                er = getattr(p0, "prediction", None)
            if er is None:
                return False
            return math.isfinite(float(er))
        except Exception as e:
            logger.warning("model_dry_run_validation_failed", error=str(e), exc_info=True)
            return False

    async def refresh_models(self) -> Dict[str, Any]:
        """Re-run model discovery and refresh required feature cache."""
        if not self.model_registry:
            raise RuntimeError("Model registry not initialized")
        from agent.models.model_discovery import ModelDiscovery

        discovery = ModelDiscovery(self.model_registry)
        discovered_models = await discovery.discover_models()
        self._required_feature_names_cache = self.model_registry.get_required_feature_names()
        if not await self.validate_models_dry_run():
            logger.warning(
                "mcp_orchestrator_model_dry_run_failed_after_refresh",
                message="Models discovered but dry-run validation failed; registry left as-is.",
            )
        logger.info(
            "mcp_orchestrator_models_refreshed",
            discovered_count=len(discovered_models),
            registry_models=len(self.model_registry.models),
            required_feature_count=len(self._required_feature_names_cache),
        )
        return {
            "discovered_models": discovered_models,
            "total_models": len(self.model_registry.models),
            "required_feature_count": len(self._required_feature_names_cache),
        }

    def _resolve_v43_bundle_metadata(self, model_name: str) -> Dict[str, Any]:
        """Load full v43 bundle metadata for multi-horizon threshold validation."""
        if not self.model_registry:
            raise RuntimeError("Model registry not initialized")
        model = self.model_registry.get_model(model_name)
        bundle_meta = getattr(model, "_bundle_metadata", None) if model is not None else None
        if isinstance(bundle_meta, dict) and isinstance(bundle_meta.get("horizons"), dict):
            return bundle_meta
        for node in self.model_registry.models.values():
            candidate = getattr(node, "_bundle_metadata", None)
            if isinstance(candidate, dict) and isinstance(candidate.get("horizons"), dict):
                return candidate
        raise ValueError(
            f"bundle metadata unavailable for model {model_name!r}; "
            "ensure metadata_ic.json is loaded on RuleBasedIntelligenceNode"
        )


    async def _process_transformer_prediction(
        self,
        symbol: str,
        context: Dict[str, Any],
        _t0: float,
    ) -> Dict[str, Any]:
        """Transformer-only path: frames -> ONNX -> threshold -> decision."""
        from agent.core.transformer_decision import evaluate_transformer_prediction

        context = _merge_prediction_context_with_agent_state(symbol, context)
        return await evaluate_transformer_prediction(
            symbol=symbol,
            context=context,
            model_registry=self.model_registry,
            delta_client=self.delta_client,
            t0=_t0,
            serialize_prediction=self._serialize_model_prediction,
        )

    async def process_prediction_request(
        self,
        symbol: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a complete prediction request through all MCP components.

        This is the main entry point for AI predictions, coordinating:
        1. Feature computation via MCP Feature Server
        2. Model inference via MCP Model Registry
        3. Reasoning synthesis via MCP Reasoning Engine

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            context: Additional context for prediction

        Returns:
            Complete prediction result with reasoning chain
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        try:
            _t0 = time.perf_counter()
            logger.info("mcp_orchestrator_prediction_start",
                       symbol=symbol,
                       context_keys=list(context.keys()) if context else None)

            context = context or {}

            if not self.model_registry or not self.model_registry.models:
                logger.warning(
                    "mcp_orchestrator_prediction_no_models",
                    symbol=symbol,
                )
                return self._create_model_error_prediction_response(
                    symbol=symbol,
                    context=context,
                    error_code="NO_MODELS_REGISTERED",
                    error_message="No ML models registered.",
                )

            return await self._process_transformer_prediction(symbol, context, _t0)

        except Exception as e:
            logger.error("mcp_orchestrator_prediction_failed",
                        symbol=symbol,
                        error=str(e),
                        exc_info=True)
            return self._create_error_prediction_response(symbol, context, str(e))

    async def get_features(
        self,
        feature_names: List[str],
        symbol: str,
        timestamp: Optional[datetime] = None
    ) -> MCPFeatureResponse:
        """
        Get features via MCP Feature Protocol.

        This is a wrapper method that delegates to the feature server.

        Args:
            feature_names: List of feature names to compute
            symbol: Trading symbol (e.g., "BTCUSD")
            timestamp: Optional timestamp for historical data

        Returns:
            MCPFeatureResponse with computed features
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        if not self.feature_server:
            raise RuntimeError("Feature server not initialized")

        request = MCPFeatureRequest(
            feature_names=feature_names,
            symbol=symbol,
            timestamp=timestamp,
            require_quality="medium"
        )

        logger.debug("mcp_orchestrator_getting_features",
                    symbol=symbol,
                    feature_count=len(feature_names))

        return await self.feature_server.get_features(request)

    async def get_trading_decision(
        self,
        symbol: str,
        market_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get trading decision with signal, confidence, and reasoning.

        This is a simplified interface that returns the core decision components
        extracted from the full prediction result.

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            market_context: Market context for decision making

        Returns:
            Dict with signal, confidence, position_size, and reasoning_chain
        """
        result = await self.process_prediction_request(symbol, market_context)

        # Extract the decision components that the agent expects
        decision = result.get("decision", {})
        reasoning = result.get("reasoning", {})

        return {
            "signal": decision.get("signal"),
            "confidence": reasoning.get("final_confidence"),
            "position_size": decision.get("position_size", 0.0),
            "reasoning_chain": {
                "chain_id": reasoning.get("chain_id"),
                "steps": reasoning.get("steps", []),
                "conclusion": reasoning.get("conclusion"),
                "final_confidence": reasoning.get("final_confidence")
            },
            "timestamp": result.get("timestamp")
        }

    def _get_required_features(self) -> List[str]:
        """Get list of required features for ML models (canonical list)."""
        # Prefer feature names required by registered models (v4 metadata order) so
        # feature server and model input align; fall back to cached values, then canonical.
        names = self.model_registry.get_required_feature_names() if self.model_registry else []
        if names:
            self._required_feature_names_cache = list(names)
            return list(names)
        if self._required_feature_names_cache:
            return list(self._required_feature_names_cache)
        logger.warning(
            "mcp_orchestrator_required_features_fallback_canonical",
            feature_count=len(get_feature_list()),
            message="Model-specific feature requirements unavailable, falling back to canonical feature list.",
        )
        return get_feature_list()

    def _create_empty_prediction_response(self, symbol: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create explicit error response when no features are available.

        This intentionally does NOT fabricate a neutral HOLD decision. Instead it
        returns an error payload that callers must treat as \"no decision\".
        """
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "success": False,
            "error_code": "NO_FEATURES",
            "error": "No features available for prediction",
            "features": {"count": 0, "quality_score": 0.0},
            "models": {
                "predictions": [],
                "consensus_prediction": 0.0,
                "healthy_models": 0,
                "total_models": 0,
            },
            "reasoning": {
                "conclusion": "Insufficient data for ML-based decision",
                "final_confidence": 0.0,
            },
        }

    def _create_model_error_prediction_response(
        self,
        symbol: str,
        context: Dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> Dict[str, Any]:
        """Create explicit error response when models cannot provide predictions."""
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "success": False,
            "error_code": error_code,
            "error": error_message,
            "context": context or {},
            "features": context.get("features") if isinstance(context, dict) else None,
            "models": {
                "predictions": [],
                "consensus_prediction": 0.0,
                "healthy_models": 0,
                "total_models": len(self.model_registry.models)
                if self.model_registry
                else 0,
            },
        }
        
    def _create_error_prediction_response(self, symbol: str, context: Dict[str, Any], error: str) -> Dict[str, Any]:
        """Create error prediction response."""
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "error": error,
            "features": {"count": 0, "quality_score": 0.0},
            "models": {"predictions": [], "consensus_prediction": 0.0, "healthy_models": 0, "total_models": 0},
            "reasoning": {"conclusion": f"HOLD - Error: {error}", "final_confidence": 0.0},
            "decision": {"signal": "HOLD", "position_size": 0.0, "confidence": 0.0},
        }

    # ------------------------------------------------------------------
    # Helpers for per-model reasoning used by downstream consumers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_signal_from_prediction(prediction: float) -> str:
        """
        Map a continuous prediction in [-1, 1] to a discrete signal.

        This is intentionally simple and is only used when an explicit
        per-model signal is not already provided by the model output.
        """
        try:
            value = float(prediction)
        except (TypeError, ValueError):
            return "HOLD"

        if value > 0.3:
            return "BUY"
        if value < -0.3:
            return "SELL"
        return "HOLD"

    def _build_model_predictions_for_reasoning(
        self, raw_predictions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize model prediction payloads for reasoning / WebSocket consumers.

        Ensures each entry includes:
        - model_name
        - reasoning
        - confidence (float 0-1 or 0-100, left as-is; downstream callers may rescale)
        - prediction (float)
        - signal (derived from prediction when missing)
        """
        normalized: List[Dict[str, Any]] = []

        for pred in raw_predictions or []:
            if not isinstance(pred, dict):
                continue

            model_name = pred.get("model_name", "Unknown")
            reasoning = pred.get("reasoning", "")
            confidence = pred.get("confidence", 0.0)
            prediction_value = pred.get("prediction", 0.0)
            signal = pred.get("signal") or self._derive_signal_from_prediction(prediction_value)
            context = pred.get("context")

            normalized.append(
                {
                    "model_name": model_name,
                    "reasoning": reasoning,
                    "confidence": confidence,
                    "prediction": prediction_value,
                    "signal": signal,
                    # Preserve model-level distribution context (e.g. entry_proba)
                    # for diagnostics and class-distribution analysis downstream.
                    "context": context,
                }
            )

        return normalized

    @staticmethod
    def _serialize_model_prediction(pred: Any) -> Dict[str, Any]:
        """Serialize model prediction while preserving model-level context."""
        ctx = getattr(pred, "context", None)
        ctx_d = ctx if isinstance(ctx, dict) else {}
        model_type = getattr(pred, "model_type", None) or ctx_d.get(
            "format", "unknown"
        )
        return {
            "model_name": pred.model_name,
            "model_version": pred.model_version,
            "prediction": pred.prediction,
            "confidence": pred.confidence,
            "reasoning": pred.reasoning,
            "features_used": getattr(pred, "features_used", []),
            "feature_importance": getattr(pred, "feature_importance", {}),
            "computation_time_ms": getattr(pred, "computation_time_ms", 0.0),
            "health_status": getattr(pred, "health_status", "healthy"),
            "model_type": model_type,
            "context": ctx,
        }

    def _build_decision_context_for_storage(
        self,
        symbol: str,
        decision: Dict[str, Any],
        market_context: Dict[str, Any],
        chain_id: str,
        timestamp: datetime,
    ) -> Optional[DecisionContext]:
        """
        Build a DecisionContext for storage in the vector store.

        Returns None if market_context or features are invalid.
        """
        if not self.vector_store:
            return None

        raw_features = market_context.get("features", {})
        if not isinstance(raw_features, dict):
            return None

        # Convert feature values to float for embedding computation
        features: Dict[str, float] = {}
        for k, v in raw_features.items():
            try:
                features[k] = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                continue

        context_id = f"decision-{chain_id}-{timestamp.timestamp():.0f}"
        dec = {
            "signal": decision.get("signal"),
            "confidence": decision.get("confidence"),
            "position_size": decision.get("position_size"),
            "reasoning_chain_id": chain_id,
            "decision_event_id": decision.get("decision_event_id"),
        }
        return DecisionContext(
            context_id=context_id,
            symbol=symbol,
            timestamp=timestamp,
            features=features,
            market_context=market_context,
            decision=dec,
            decision_event_id=decision.get("decision_event_id"),
        )

    async def _memory_context_count(self) -> int:
        if not self.vector_store:
            return 0
        try:
            stats = await self.vector_store.get_memory_stats()
            return int(stats.get("total_contexts", 0) or 0)
        except Exception:
            return 0


    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of MCP components."""
        health_status = {
            "mcp_orchestrator": {
                "status": "healthy" if self._initialized else "unhealthy",
                "initialized": self._initialized,
                "components": {},
            }
        }
        if self.feature_server:
            try:
                health_status["mcp_orchestrator"]["components"]["feature_server"] = (
                    await self.feature_server.get_health_status()
                )
            except Exception as e:
                health_status["mcp_orchestrator"]["components"]["feature_server"] = {
                    "status": "unknown",
                    "error": str(e),
                }
        if self.model_registry:
            try:
                health_status["mcp_orchestrator"]["components"]["model_registry"] = (
                    await self.model_registry.get_health_status()
                )
            except Exception as e:
                health_status["mcp_orchestrator"]["components"]["model_registry"] = {
                    "status": "unknown",
                    "error": str(e),
                }
        return health_status

    def _schedule_prediction_audit(
        self,
        *,
        correlation_id: str,
        symbol: str,
        confidence: float,
        decision_payload: Dict[str, Any],
        latency_ms: Optional[float] = None,
    ) -> None:
        """Fire-and-forget insert into prediction_audit (non-blocking)."""
        if not getattr(settings, "prediction_audit_writes_enabled", True):
            logger.info(
                "prediction_audit_skipped_disabled",
                correlation_id=correlation_id,
                symbol=symbol,
                message="prediction_audit write skipped because feature flag is disabled.",
            )
            return
        db_url = getattr(settings, "database_url", None)
        if not db_url:
            logger.warning(
                "prediction_audit_skipped_no_database_url",
                correlation_id=correlation_id,
                symbol=symbol,
                message="prediction_audit write skipped because DATABASE_URL is missing.",
            )
            return

        from agent.persistence.db_writes import persist_prediction_audit_async

        rc = decision_payload.get("reasoning_chain") or {}
        model_predictions = rc.get("model_predictions") or []
        inferred_versions = []
        if isinstance(model_predictions, list):
            for p in model_predictions:
                if isinstance(p, dict):
                    mv = p.get("model_version")
                    if isinstance(mv, str) and mv.strip():
                        inferred_versions.append(mv.strip())
        versions = sorted(set(inferred_versions))
        model_version_for_row = versions[0] if len(versions) == 1 else None
        meta: Dict[str, Any] = {
            "correlation_id": correlation_id,
            "signal": decision_payload.get("signal"),
            "position_size": decision_payload.get("position_size"),
            "reasoning_chain_id": rc.get("chain_id"),
            "conclusion": (rc.get("conclusion") or "")[:500],
            "model_prediction_count": len(rc.get("model_predictions") or []),
            "model_versions": versions,
        }

        async def _run() -> None:
            await persist_prediction_audit_async(
                db_url,
                symbol=symbol,
                confidence=float(confidence) if confidence is not None else None,
                latency_ms=latency_ms,
                source="agent_mcp",
                model_version=model_version_for_row,
                outcome_reference=correlation_id,
                metadata=meta,
                request_id=str(uuid.uuid4()),
            )

        try:
            from agent.core.async_tasks import fire_and_forget

            fire_and_forget(_run(), name="prediction_audit_write")
        except Exception as e:
            logger.warning("prediction_audit_schedule_failed", error=str(e))


    async def _handle_prediction_request(self, event: ModelPredictionRequestEvent):
        """Handle prediction request event and emit DecisionReadyEvent."""
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            context = payload.get("context", {})

            result = await self.process_prediction_request(symbol, context)
            completion_event = ModelPredictionCompleteEvent(
                source="mcp_orchestrator",
                correlation_id=event.event_id,
                payload=result,
            )
            await event_bus.publish(completion_event)
            if result.get("error") is not None:
                return

            decision = result.get("decision") or {}
            if not isinstance(decision, dict) or decision.get("signal") is None:
                return

            reasoning = result.get("reasoning") or {}
            decision_symbol = result.get("symbol") or symbol
            timestamp = result.get("timestamp") or datetime.now(timezone.utc)
            pv_raw = result.get("policy_verdict")
            if not isinstance(pv_raw, dict):
                return
            verdict = PolicyVerdict(**pv_raw)
            signal = verdict.signal
            position_size = float(verdict.position_size or 0.0)
            confidence = float(verdict.confidence or 0.0)

            _entry_signals = frozenset({"BUY", "SELL", "STRONG_BUY", "STRONG_SELL"})
            mctx = result.get("market_context") if isinstance(result.get("market_context"), dict) else {}
            bar_idx = mctx.get("closed_bar_index")
            if signal == "HOLD" and bar_idx is not None and self._last_entry_decision_bar == int(bar_idx):
                return
            if signal in _entry_signals and bar_idx is not None:
                bar_i = int(bar_idx)
                if self._last_entry_decision_bar == bar_i:
                    return
                self._last_entry_decision_bar = bar_i

            model_predictions_for_reasoning = self._build_model_predictions_for_reasoning(
                result.get("model_predictions") or []
            )
            reasoning_chain_payload: Dict[str, Any] = {
                "chain_id": reasoning.get("chain_id"),
                "steps": reasoning.get("steps", []),
                "conclusion": reasoning.get("conclusion"),
                "final_confidence": reasoning.get("final_confidence"),
                "signal_strength": reasoning.get("signal_strength"),
                "model_predictions": model_predictions_for_reasoning,
                "market_context": mctx,
            }
            decision_payload = {
                "symbol": decision_symbol,
                "signal": signal,
                "confidence": confidence,
                "position_size": position_size,
                "reasoning_chain": reasoning_chain_payload,
                "timestamp": timestamp,
                "policy_authority": PolicyAuthority.AGENT_POLICY.value,
                "policy_reason_codes": list(verdict.reason_codes or []),
                "policy_verdict": verdict.model_dump(mode="json"),
                "strategy_origin": False,
            }
            decision_payload.update(_decision_ws_metadata(result))
            _enrich_confidence_semantics(decision_payload)
            decision_event = DecisionReadyEvent(
                source="transformer_decision",
                correlation_id=event.event_id,
                payload=decision_payload,
            )
            if getattr(settings, "agent_introspection_enabled", True):
                intro = build_introspection_snapshot(
                    symbol=decision_symbol,
                    signal=signal,
                    confidence=confidence,
                    policy_reason_codes=list(verdict.reason_codes or []),
                    policy_verdict=verdict.model_dump(mode="json"),
                    ml_evidence_snapshot={},
                    market_context=mctx,
                    trade_score=None,
                    memory_enabled=bool(self.vector_store),
                    memory_context_count=await self._memory_context_count(),
                )
                decision_event.payload["agent_introspection"] = intro.to_dict()
            await event_bus.publish(decision_event)
            self._schedule_prediction_audit(
                correlation_id=event.event_id,
                symbol=decision_symbol,
                confidence=confidence,
                decision_payload=decision_event.payload,
                latency_ms=result.get("inference_latency_ms"),
            )
            logger.info(
                "mcp_orchestrator_decision_ready_emitted",
                symbol=decision_symbol,
                signal=signal,
                confidence=confidence,
                position_size=position_size,
                event_id=decision_event.event_id,
                correlation_id=event.event_id,
            )
        except Exception as e:
            logger.error(
                "mcp_orchestrator_prediction_request_failed",
                event_id=event.event_id,
                error=str(e),
                exc_info=True,
            )



    async def _persist_v43_gate_state_locked(self, symbol: str) -> None:
        return None

    def record_v43_signal_decision(self, bar_index: int) -> None:
        return None

    def rollback_v43_signal_decision(self, bar_index: Optional[int] = None) -> None:
        return None

    def record_v43_trade_executed(self, bar_index: int) -> None:
        return None

    async def persist_v43_gate_state_after_trade(self, symbol: str) -> None:
        return None



# Create global MCP orchestrator instance
mcp_orchestrator = MCPOrchestrator()