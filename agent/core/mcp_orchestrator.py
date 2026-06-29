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
from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, MCPReasoningChain
from agent.memory.vector_store import VectorMemoryStore, DecisionContext
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    ModelPredictionRequestEvent,
    ModelPredictionCompleteEvent,
    DecisionReadyEvent,
    EventType,
    PolicyAuthority,
    PolicyVerdict,
    MLEvidenceSnapshot,
)
from agent.core.agent_policy_engine import (
    agent_policy_engine,
    build_ml_evidence_from_orchestrator_result,
)
from agent.core.config import settings
from agent.core.evidence_engine import build_evidence_bundle, market_forecast_from_context
from agent.core.conviction import compute_conviction
from agent.core.gate_profile import (
    evidence_based_sizing_enabled,
    trade_score_hard_veto_enabled,
    v43_soft_ml_gates_enabled,
)
from agent.core.abstention import abstention_from_reason_codes
from agent.core.signal_vocabulary import (
    ENTRY_SIGNALS,
    is_entry_signal,
    is_long_signal,
    is_short_signal,
    normalize_signal,
    signal_to_position_side,
)
from agent.core.agent_introspection import build_introspection_snapshot
from agent.core.v43_market_frames import V43_MIN_5M_ROWS, closed_5m_bar_index
from agent.core.v43_signal_gates import (
    V43GateResult,
    V43GateState,
    apply_gate5_min_edge,
    apply_gate5_min_edge_short,
    apply_uncertainty_gate,
    apply_post_threshold_gates,
    apply_post_threshold_gates_short,
    compute_regime_transition_risk,
    load_gate_state_from_redis,
    maybe_widen_epsilon_on_high_collapse,
    persist_gate_state,
)
from agent.core.log_context import (
    EVENT_MODEL_PREDICTION,
    KEY_FEATURE_QUALITY,
    KEY_SYMBOL,
)
from feature_store.feature_registry import get_feature_list
from agent.core.v43_runtime_horizon import set_runtime_v43_horizon
from agent.core.multi_horizon_evidence import (
    build_multi_horizon_evidence,
    primary_head_for_gates,
)
from feature_store.jacksparrow_v43_horizon import (
    V43_SUPPORTED_FORWARD_TARGET_BARS,
    build_execution_profile,
    forward_bars_to_minutes,
    resolve_training_forward_bars,
)
from feature_store.jacksparrow_v43_multihead import primary_execution_horizon_bars

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
    from agent.core.display_metrics import build_display_metrics

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
    signal = normalize_signal(payload.get("signal") or "HOLD")
    actionable = is_entry_signal(signal)
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

    mc = None
    preds = None
    if isinstance(reasoning_chain, dict):
        mc = reasoning_chain.get("market_context")
        preds = reasoning_chain.get("model_predictions")
    payload.update(
        build_display_metrics(
            signal=str(signal),
            policy_confidence=policy_conf,
            reasoning_chain=reasoning_chain if isinstance(reasoning_chain, dict) else None,
            market_context=mc if isinstance(mc, dict) else None,
            model_predictions=preds if isinstance(preds, list) else None,
            payload=payload,
        )
    )


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
        self.reasoning_engine: Optional[MCPReasoningEngine] = None
        self.vector_store: Optional[VectorMemoryStore] = None
        self._required_feature_names_cache: List[str] = []
        self.delta_client = None  # Set by agent for 15m trend (MTF confirmation)
        self.market_data_manager: Optional[Any] = None
        self._initialized = False
        self._v43_gate_state = V43GateState()
        self._v43_gate_state_lock = asyncio.Lock()
        self._prediction_lock = asyncio.Lock()
        self._v43_gate_symbol: Optional[str] = None
        self._v43_last_entry_decision_bar: Optional[int] = None
    
    async def initialize(self, market_data_service: Optional[Any] = None):
        """Initialize all MCP components."""
        try:
            logger.info("mcp_orchestrator_initializing", message="Starting MCP Orchestrator initialization")

            # Initialize MCP Feature Server
            self.feature_server = MCPFeatureServer(market_data_service=market_data_service)
            self.market_data_manager = market_data_service
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

            # Initialize Vector Memory Store for historical context retrieval (Step 2)
            from agent.memory.vector_store_factory import create_vector_store

            self.vector_store = await create_vector_store()
            self.learning_system = None

            # Initialize MCP Reasoning Engine
            self.reasoning_engine = MCPReasoningEngine(
                feature_server=self.feature_server,
                model_registry=self.model_registry,
                vector_store=self.vector_store,
                learning_system=self.learning_system,
            )
            await self.reasoning_engine.initialize()
            logger.info("mcp_orchestrator_reasoning_engine_initialized")

            # Register event handlers
            event_bus.subscribe(EventType.MODEL_PREDICTION_REQUEST, self._handle_prediction_request)

            gate_symbol = str(getattr(settings, "trading_symbol", "BTCUSD") or "BTCUSD").upper()
            self._v43_gate_symbol = gate_symbol
            try:
                from agent.core.redis_config import get_redis

                redis_client = await get_redis()
                self._v43_gate_state = await load_gate_state_from_redis(
                    gate_symbol,
                    redis_client,
                )
                logger.info(
                    "v43_gate_state_loaded",
                    symbol=gate_symbol,
                    last_signal_bar=self._v43_gate_state.last_signal_bar_index,
                    trades_today=sum(self._v43_gate_state.trades_by_date.values()),
                )
            except Exception as e:
                logger.warning("v43_gate_state_load_skipped", error=str(e))

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

            if self.reasoning_engine:
                await self.reasoning_engine.shutdown()

            if self.vector_store:
                await self.vector_store.shutdown()
                self.vector_store = None

            if self.model_registry:
                await self.model_registry.shutdown()

            if self.feature_server:
                await self.feature_server.shutdown()

            if self._v43_gate_symbol:
                try:
                    from agent.core.redis_config import get_redis

                    redis_client = await get_redis()
                    await persist_gate_state(
                        self._v43_gate_symbol,
                        self._v43_gate_state,
                        redis_client,
                    )
                except Exception as e:
                    logger.warning("v43_gate_state_shutdown_persist_failed", error=str(e))

    
            logger.info("mcp_orchestrator_shutdown_complete")

        except Exception as e:
            logger.error("mcp_orchestrator_shutdown_failed", error=str(e), exc_info=True)

    async def validate_models_dry_run(self) -> bool:
        """Verify registered models are load-ready without a full IC predict cycle.

        Rule-based IC nodes require v43 market frames for predict(); warmup only
        checks initialization. Legacy ML nodes still use a zero-feature dry run.
        """
        import math

        if not self.model_registry or not self.model_registry.models:
            return False
        try:
            from agent.models.mcp_model_node import MCPModelRequest

            symbol = getattr(settings, "trading_symbol", "BTCUSD")
            all_ok = True

            for model_name, model in self.model_registry.models.items():
                if getattr(model, "model_type", "") == "rule_based_intelligence":
                    health = await model.get_health_status()
                    if not health.get("initialized"):
                        logger.warning(
                            "ic_dry_run_not_initialized",
                            model_name=model_name,
                        )
                        all_ok = False
                        continue
                    logger.info("ic_dry_run_load_ok", model_name=model_name)
                    continue

                names = self._required_feature_names_cache or get_feature_list()
                feats = [0.0] * max(1, len(names))
                req = MCPModelRequest(
                    request_id="dry_run_validation",
                    features=feats,
                    context={"dry_run": True, "symbol": symbol},
                )
                resp = await self.model_registry.get_predictions(req)
                preds = getattr(resp, "predictions", None) or []
                if not preds:
                    all_ok = False
                    continue
                p0 = preds[0]
                ctx = getattr(p0, "context", None) or {}
                er = ctx.get("expected_return") if isinstance(ctx, dict) else None
                if er is None:
                    er = getattr(p0, "prediction", None)
                if er is None or not math.isfinite(float(er)):
                    all_ok = False

            return all_ok
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

    def _maybe_apply_rule_based_pipeline(
        self,
        *,
        symbol: str,
        bar_idx: int,
        features_dict: Dict[str, Any],
        regime: str,
        structure: Any,
        thesis_verdict: Any,
        has_open: bool,
        contract_state: Any,
        market_context: Dict[str, Any],
        policy_verdict: Any,
        pos_hint: float,
        df_feat: Any = None,
    ) -> Any:
        """Run rule-based pipeline (shadow or enforce) and optionally override policy."""
        from agent.core.signal_vocabulary import ENTRY_SIGNALS, is_entry_signal
        from agent.intelligence.market_understanding_engine import features_history_from_matrix
        from agent.intelligence.rule_based_pipeline import (
            is_shadow_enabled,
            log_shadow_comparison,
            rule_based_pipeline,
            should_enforce_fsm,
        )
        from agent.events.schemas import PolicyVerdict

        if not is_shadow_enabled() and not should_enforce_fsm():
            return policy_verdict

        thesis_type = str(getattr(thesis_verdict, "thesis_type", "flat") or "flat")
        thesis_signal = str(getattr(thesis_verdict, "signal", "HOLD") or "HOLD")
        feat_hist = features_history_from_matrix(df_feat) if df_feat is not None else None
        rb = rule_based_pipeline.run_cycle(
            symbol=symbol,
            bar_index=bar_idx,
            features=features_dict,
            regime=regime,
            thesis_signal=thesis_signal,
            thesis_type=thesis_type,
            has_open_position=has_open,
            structure=structure,
            gate_state=self._v43_gate_state,
            contract_state=contract_state,
            features_history=feat_hist,
        )
        market_context["rule_based_pipeline"] = rb.to_dict()
        market_context["market_state"] = rb.market_state.to_dict()
        market_context["narrative_tail"] = rb.narrative_tail
        market_context["structural_gates"] = rb.structural_gates.to_dict()
        market_context["fsm_state"] = rb.fsm_decision.fsm_state
        market_context["entry_signal"] = rb.fsm_decision.entry_signal
        market_context["thesis_health"] = rb.fsm_decision.thesis_health
        market_context["position_lifecycle"] = rb.fsm_decision.position_lifecycle

        from agent.intelligence.trade_archetype_memory import trade_archetype_memory

        sim = trade_archetype_memory.similar_setups(
            symbol,
            setup_type=rb.structural_gates.setup_type,
            regime=regime,
            narrative_tail=rb.narrative_tail,
        )
        market_context["archetype_similarity"] = sim

        live_entry = policy_verdict.signal in ENTRY_SIGNALS
        log_shadow_comparison(
            symbol=symbol,
            pipeline=rb,
            live_signal=policy_verdict.signal,
            live_is_entry=live_entry,
        )

        if not should_enforce_fsm():
            return policy_verdict

        fsm_sig = rb.fsm_decision.entry_signal
        reasons = list(policy_verdict.reason_codes or [])
        if is_entry_signal(fsm_sig) and rb.structural_gates.trade_allowed:
            reasons.append("rule_based_fsm_entry")
            size = float(pos_hint) * float(rb.position_size_fraction or 0.0)
            if size <= 0:
                size = float(pos_hint) * 0.5
            return PolicyVerdict(
                signal=fsm_sig,
                confidence=float(rb.structural_confidence),
                position_size=size,
                reason_codes=reasons,
                adopted_ml_candidate=False,
                conviction=rb.structural_confidence,
                size_fraction=rb.position_size_fraction,
            )
        reasons.append(rb.fsm_decision.abstention_reason or "fsm_hold")
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(policy_verdict.confidence or 0.0),
            position_size=0.0,
            reason_codes=reasons,
            adopted_ml_candidate=False,
            conviction=rb.structural_confidence,
            size_fraction=0.0,
            abstention=rb.fsm_decision.abstention_reason,
        )

    async def _process_jacksparrow_v43_prediction(
        self,
        symbol: str,
        context: Dict[str, Any],
        _t0: float,
    ) -> Dict[str, Any]:
        """Strategy-first v43 path: frames → ML validation → thesis → score → policy → reasoning."""
        from agent.core.agent_thesis_engine import agent_thesis_engine
        from agent.core.market_structure import classify_market_structure
        from agent.core.ml_validator import (
            apply_gates_to_ml_validation,
            build_ml_validation_from_prediction,
            ml_confirms_direction,
            ml_candidate_signal_from_validation,
            thesis_verdict_to_strategy_candidate,
        )
        from agent.core.trade_scorer import score_trade_setup
        from agent.data.incremental_feature_engine import incremental_feature_engine
        from agent.data.market_data_manager import MarketDataManager
        from agent.intelligence.market_intelligence import MarketIntelligence
        from agent.intelligence.market_intelligence_diff import (
            diff_market_intelligence,
            should_run_full_prediction,
        )
        from agent.intelligence.market_intelligence_store import market_intelligence_store

        if not self.delta_client:
            logger.warning(
                "mcp_orchestrator_v43_no_delta_client",
                symbol=symbol,
                message="delta_client not set; cannot fetch v43 OHLCV frames",
            )
            return self._create_empty_prediction_response(
                symbol, context, reason="delta_client_unavailable"
            )

        context = _merge_prediction_context_with_agent_state(symbol, context)

        manager = self.market_data_manager
        if isinstance(manager, MarketDataManager):
            bundle = await manager.get_v43_frames(symbol)
            df5, df15, df1h, df_fund, df_oi, df_mark = (
                bundle.df5m,
                bundle.df15m,
                bundle.df1h,
                bundle.df_funding,
                bundle.df_oi,
                bundle.df_mark,
            )
        else:
            from agent.core.v43_market_frames import fetch_v43_market_frames

            df5, df15, df1h, df_fund, df_oi, df_mark = await fetch_v43_market_frames(
                self.delta_client, symbol
            )
            try:
                if self.feature_server and getattr(
                    self.feature_server, "market_data_service", None
                ):
                    mtf = settings.resolved_agent_timeframes()
                    if mtf:
                        await self.feature_server.market_data_service.warm_multi_timeframe_caches(
                            str(symbol),
                            mtf,
                        )
            except Exception as warm_err:
                logger.debug(
                    "v43_mtf_cache_warm_skipped",
                    symbol=symbol,
                    error=str(warm_err),
                )

        if df5.empty or len(df5) < V43_MIN_5M_ROWS:
            return self._create_empty_prediction_response(
                symbol,
                context,
                reason=f"insufficient_5m_rows:{len(df5) if not df5.empty else 0}<{V43_MIN_5M_ROWS}",
                df5_rows=len(df5) if not df5.empty else 0,
            )

        import pandas as pd

        from agent.core.v43_contract_state import get_contract_state
        from agent.core.v43_market_frames import closed_5m_bar_index
        from agent.intelligence.ic_node import build_closed_feats_from_v43_dataframes
        from agent.intelligence.regime_classifier import classify_regime
        from agent.core.agent_thesis_engine import (
            agent_thesis_engine,
            get_last_hypothesis_snapshot,
            thesis_verdict_to_dict,
        )

        ticker_row: Dict[str, Any] = {}
        if isinstance(df_oi, pd.DataFrame) and not df_oi.empty:
            ticker_row = df_oi.iloc[-1].to_dict()
        contract_state = await get_contract_state(symbol, ticker_row=ticker_row)

        req_id = f"pred_v43_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        mctx = {
            **context,
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": df_oi,
            "v43_df_mark": df_mark,
            "v43_contract_state": contract_state,
            "current_price": context.get("current_price"),
            "symbol": symbol,
        }
        if isinstance(df_oi, pd.DataFrame) and not df_oi.empty:
            last_oi = df_oi.iloc[-1]
            oi_val = last_oi.get("oi_contracts") if hasattr(last_oi, "get") else None
            if oi_val is None and "oi_contracts" in df_oi.columns:
                oi_val = last_oi["oi_contracts"]
            if oi_val is not None:
                try:
                    mctx["mso_oi_contracts"] = float(oi_val)
                except (TypeError, ValueError):
                    pass
            ts_raw = last_oi.get("timestamp") if hasattr(last_oi, "get") else None
            if ts_raw is None and "timestamp" in df_oi.columns:
                ts_raw = last_oi["timestamp"]
            if ts_raw is not None:
                try:
                    mctx["mso_oi_snapshot_ts"] = float(pd.Timestamp(ts_raw).timestamp())
                except (TypeError, ValueError):
                    pass
        if not contract_state.is_operational:
            mctx["v43_market_health_hold"] = True
            mctx["v43_market_health_reason"] = (
                f"contract_state={contract_state.state} "
                f"trading_status={contract_state.trading_status} "
                f"reduce_only={contract_state.only_reduce_only_orders_allowed}"
            )

        try:
            closed_feats_pre, df_feat_pre = await asyncio.to_thread(
                incremental_feature_engine.update_from_frames,
                symbol,
                df5,
                df15,
                df1h,
                df_fund,
                df_oi=df_oi,
                df_mark=df_mark,
            )
        except ValueError:
            try:
                closed_feats_pre, df_feat_pre = await asyncio.to_thread(
                    build_closed_feats_from_v43_dataframes,
                    df5,
                    df15,
                    df1h,
                    df_fund,
                    df_oi=df_oi,
                    df_mark=df_mark,
                )
            except ValueError as feat_err:
                logger.warning(
                    "v43_feature_matrix_batch_fallback_failed",
                    symbol=symbol,
                    df5_rows=len(df5) if not df5.empty else 0,
                    error=str(feat_err),
                )
                return self._create_empty_prediction_response(
                    symbol,
                    context,
                    reason="v43_feature_matrix_build_failed",
                    df5_rows=len(df5) if not df5.empty else 0,
                )

        has_open_pre = bool(context.get("has_open_position", False))
        if not has_open_pre:
            has_open_pre = await _exchange_has_open_position_async(symbol)

        regime_pre = classify_regime(closed_feats_pre)
        if "regime_label" in closed_feats_pre:
            regime_pre = str(closed_feats_pre.get("regime_label", regime_pre))

        features_pre: Dict[str, Any] = {
            str(k): float(v) for k, v in closed_feats_pre.items()
        }
        if "volatility" not in features_pre:
            atr_pre = features_pre.get("atr_pct")
            if atr_pre is not None:
                features_pre["volatility"] = float(atr_pre) * 100.0

        structure_pre = classify_market_structure(
            features_pre,
            v43_regime=regime_pre,
            contract_state=contract_state,
        )
        thesis_mc_pre: Dict[str, Any] = {
            **(context or {}),
            "symbol": symbol,
            "features": features_pre,
            "regime": regime_pre,
            "v43_regime": regime_pre,
            "market_structure": structure_pre.to_dict(),
            "has_open_position": has_open_pre,
            "v43_contract_state": contract_state,
            "price_band_proximity": {
                "dist_upper_pct": contract_state.dist_to_upper_band_pct(),
                "dist_lower_pct": contract_state.dist_to_lower_band_pct(),
            },
        }
        if mctx.get("v43_market_health_hold"):
            thesis_mc_pre["market_health_hold"] = True
            thesis_mc_pre["market_health_reason"] = mctx.get("v43_market_health_reason")

        thesis_verdict_cached = agent_thesis_engine.evaluate(regime_pre, thesis_mc_pre)
        mctx["thesis_verdict"] = thesis_verdict_to_dict(thesis_verdict_cached)
        _hyp_snap = get_last_hypothesis_snapshot()
        if _hyp_snap:
            mctx["hypothesis_snapshot"] = _hyp_snap
            if isinstance(_hyp_snap.get("environment"), dict):
                mctx["environment_scores"] = dict(_hyp_snap["environment"])
        mctx["closed_feats_pre"] = closed_feats_pre
        mctx["df_feat_pre"] = df_feat_pre
        mctx["regime"] = regime_pre
        mctx["v43_regime"] = regime_pre
        mctx["market_structure"] = structure_pre.to_dict()

        bar_idx = int(closed_5m_bar_index(df5))
        if bool(getattr(settings, "market_intelligence_enabled", True)):
            intel = MarketIntelligence.from_cycle(
                symbol=symbol,
                bar_index=bar_idx,
                closed_feats=closed_feats_pre,
                structure=structure_pre,
                contract_state=contract_state,
                thesis_verdict=mctx["thesis_verdict"],
            )
            prev_intel = market_intelligence_store.get(symbol)
            material = diff_market_intelligence(prev_intel, intel)
            intel = await market_intelligence_store.put(intel)
            mctx["market_intelligence"] = intel.to_dict()
            mctx["market_intel_material_change"] = {
                "changed": material.changed,
                "reasons": list(material.reasons),
            }

            try:
                from agent.core.context_manager import context_manager

                await context_manager.update_state(
                    {"market_regime": intel.regime, "volatility_regime": intel.volatility_state}
                )
            except Exception:
                pass

            if bool(getattr(settings, "market_intel_diff_log_only", True)) and material.changed:
                logger.info(
                    "market_intelligence_material_change",
                    symbol=symbol,
                    reasons=material.reasons,
                    version=intel.version,
                )

            if not should_run_full_prediction(
                material,
                has_open_position=has_open_pre,
            ):
                try:
                    from agent.intelligence.rule_based_pipeline import (
                        is_shadow_enabled,
                        log_shadow_comparison,
                        rule_based_pipeline,
                    )

                    if is_shadow_enabled():
                        from agent.intelligence.market_understanding_engine import (
                            features_history_from_matrix,
                        )

                        features_pre_dict = {
                            str(k): float(v) for k, v in closed_feats_pre.items()
                        }
                        rb = rule_based_pipeline.run_cycle(
                            symbol=symbol,
                            bar_index=bar_idx,
                            features=features_pre_dict,
                            regime=regime_pre,
                            thesis_signal=str(thesis_verdict_cached.signal),
                            thesis_type=str(thesis_verdict_cached.thesis_type),
                            has_open_position=has_open_pre,
                            structure=structure_pre,
                            gate_state=self._v43_gate_state,
                            contract_state=contract_state,
                            features_history=features_history_from_matrix(df_feat_pre),
                        )
                        log_shadow_comparison(
                            symbol=symbol,
                            pipeline=rb,
                            live_signal="HOLD",
                            live_is_entry=False,
                        )
                except Exception as shadow_err:
                    logger.debug(
                        "rule_based_shadow_intel_skip_failed",
                        symbol=symbol,
                        error=str(shadow_err),
                    )
                logger.info(
                    "prediction_skipped_intel_unchanged",
                    symbol=symbol,
                    bar_index=bar_idx,
                    reasons=material.reasons,
                )
                return self._create_empty_prediction_response(
                    symbol,
                    context,
                    reason="intel_unchanged_skip",
                    bar_index=bar_idx,
                )

        model_request = MCPModelRequest(
            request_id=req_id,
            features=[],
            context=mctx,
            require_explanation=True,
        )
        try:
            model_response = await self.model_registry.get_predictions(model_request)
        except (NoModelsRegisteredError, NoHealthyModelPredictionsError) as e:
            return self._create_model_error_prediction_response(
                symbol=symbol,
                context=context,
                error_code=type(e).__name__,
                error_message=str(e),
            )

        pred0 = model_response.predictions[0]
        pctx = pred0.context if isinstance(pred0.context, dict) else {}
        head_payloads = pctx.get("multi_horizon_heads")
        if not isinstance(head_payloads, dict) or not head_payloads:
            return self._create_model_error_prediction_response(
                symbol=symbol,
                context=context,
                error_code="V43MultiHeadMissing",
                error_message="v43 prediction missing multi_horizon_heads (retrain multi-head bundle)",
            )
        try:
            bundle_metadata = self._resolve_v43_bundle_metadata(pred0.model_name)
        except (RuntimeError, ValueError) as e:
            return self._create_model_error_prediction_response(
                symbol=symbol,
                context=context,
                error_code=type(e).__name__,
                error_message=str(e),
            )
        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )
        eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)
        mh_evidence = build_multi_horizon_evidence(
            head_payloads,
            bundle_metadata,
            short_enabled=short_enabled,
            eps=eps,
        )
        gate_head = primary_head_for_gates(mh_evidence)
        training_forward_bars = int(
            gate_head.forward_bars or primary_execution_horizon_bars(bundle_metadata)
        )
        align_horizon = bool(
            getattr(settings, "jacksparrow_v43_align_execution_to_horizon", True)
        )
        v43_execution_profile = build_execution_profile(
            training_forward_bars,
            align=align_horizon,
            debounce_override=(
                None
                if align_horizon
                else int(getattr(settings, "jacksparrow_v43_trade_debounce_bars", 2) or 2)
            ),
            max_hold_hours_override=(
                None
                if align_horizon
                else float(getattr(settings, "max_position_hold_hours", 24) or 24)
            ),
            take_profit_pct_override=(
                None
                if align_horizon
                else float(getattr(settings, "jacksparrow_v43_take_profit_pct", 0.01) or 0.01)
            ),
        )
        set_runtime_v43_horizon(
            training_forward_bars, execution_profile=v43_execution_profile
        )
        horizon_minutes = forward_bars_to_minutes(training_forward_bars)
        proba = float(gate_head.expected_return)
        thr = float(gate_head.threshold)
        short_thr = float(gate_head.short_threshold)
        regime = str(gate_head.regime or pctx.get("regime", "neutral") or "neutral")
        u_scale = float(pctx.get("unc_scale", 1.0) or 1.0)
        _raw_unc = pctx.get("uncertainty_score", pctx.get("uncertainty"))
        uncertainty_score: Optional[float] = None
        if _raw_unc is not None:
            try:
                uncertainty_score = float(_raw_unc)
            except (TypeError, ValueError):
                uncertainty_score = None
        p_regime_favorable = pctx.get("p_regime_favorable")
        p_setup_quality = pctx.get("p_setup_quality")
        p_vol_expansion = pctx.get("p_vol_expansion")
        closed_feats = pctx.get("closed_bar_features") or {}
        if not isinstance(closed_feats, dict):
            closed_feats = {}

        bar_idx = closed_5m_bar_index(df5)
        has_open = bool(context.get("has_open_position", False))
        if not has_open:
            has_open = await _exchange_has_open_position_async(symbol)

        ml_validation = build_ml_validation_from_prediction(
            pctx,
            pred_confidence=float(pred0.confidence),
            pred_value=float(pred0.prediction),
            eps=eps,
            short_enabled=short_enabled,
        )
        proba = ml_validation.expected_return
        thr = ml_validation.threshold
        short_thr = ml_validation.short_threshold
        raw_long = ml_validation.raw_long
        raw_short = ml_validation.raw_short

        features_dict: Dict[str, Any] = {str(k): float(v) for k, v in closed_feats.items()}
        if "volatility" not in features_dict:
            atr = features_dict.get("atr_pct")
            if atr is not None:
                features_dict["volatility"] = float(atr) * 100.0

        structure = classify_market_structure(
            features_dict,
            v43_regime=regime,
            contract_state=contract_state,
        )
        thesis_mc: Dict[str, Any] = {
            **(context or {}),
            "symbol": symbol,
            "features": features_dict,
            "regime": regime,
            "v43_regime": regime,
            "market_structure": structure.to_dict(),
            "has_open_position": has_open,
            "v43_contract_state": contract_state,
            "price_band_proximity": {
                "dist_upper_pct": contract_state.dist_to_upper_band_pct(),
                "dist_lower_pct": contract_state.dist_to_lower_band_pct(),
            },
        }
        if mctx.get("v43_market_health_hold"):
            thesis_mc["market_health_hold"] = True
            thesis_mc["market_health_reason"] = mctx.get("v43_market_health_reason")
        thesis_verdict = thesis_verdict_cached
        _ic_thesis_pre_reconcile = str(pctx.get("ic_thesis_signal") or "").upper()
        _policy_thesis = str(thesis_verdict.signal).upper()
        if _ic_thesis_pre_reconcile and _ic_thesis_pre_reconcile != _policy_thesis:
            logger.warning(
                "ic_thesis_policy_divergence",
                ic_thesis_pre_reconcile=_ic_thesis_pre_reconcile,
                policy_thesis=_policy_thesis,
                has_open_position=has_open,
                message=(
                    "IC pre-reconcile thesis differs from policy-level thesis. "
                    "Agent will act on policy_thesis. Frontend ic_thesis_signal "
                    "is tagged ic_thesis_signal_is_pre_reconcile=True."
                ),
            )
        strategy_candidate = thesis_verdict_to_strategy_candidate(thesis_verdict)

        thesis_h_bars = int(
            strategy_candidate.intended_horizon_bars
            or thesis_verdict.intended_horizon_bars
            or 0
        )
        exec_bars = (
            thesis_h_bars
            if thesis_h_bars in V43_SUPPORTED_FORWARD_TARGET_BARS
            else training_forward_bars
        )
        if exec_bars != training_forward_bars:
            align_horizon = bool(
                getattr(settings, "jacksparrow_v43_align_execution_to_horizon", True)
            )
            v43_execution_profile = build_execution_profile(
                exec_bars,
                align=align_horizon,
                debounce_override=(
                    None
                    if align_horizon
                    else int(
                        getattr(settings, "jacksparrow_v43_trade_debounce_bars", 2) or 2
                    )
                ),
                max_hold_hours_override=(
                    None
                    if align_horizon
                    else float(getattr(settings, "max_position_hold_hours", 24) or 24)
                ),
                take_profit_pct_override=(
                    None
                    if align_horizon
                    else float(
                        getattr(settings, "jacksparrow_v43_take_profit_pct", 0.01) or 0.01
                    )
                ),
            )
            set_runtime_v43_horizon(exec_bars, execution_profile=v43_execution_profile)
            horizon_minutes = forward_bars_to_minutes(exec_bars)

        final_long = False
        final_short = False
        reject_tail = "below_threshold"
        eps_eff = float(eps) + float(self._v43_gate_state.effective_epsilon_bump())

        soft_ml_gates = v43_soft_ml_gates_enabled()

        async with self._v43_gate_state_lock:
            self._v43_gate_state.note_regime(regime)
            if raw_long:
                gr2 = apply_post_threshold_gates(
                    raw_long=raw_long,
                    regime=regime,
                    current_bar_index=bar_idx,
                    has_open_position=has_open,
                    state=self._v43_gate_state,
                )
                reject_tail = gr2.reject_reason or "below_threshold"
                if gr2.allow:
                    if (
                        bool(getattr(settings, "jacksparrow_v43_state_heads_enabled", False))
                        and not soft_ml_gates
                    ):
                        gu = apply_uncertainty_gate(
                            uncertainty_score, self._v43_gate_state
                        )
                        if not gu.allow:
                            reject_tail = gu.reject_reason or "high_uncertainty"
                            gr2 = V43GateResult(allow=False, reject_reason=reject_tail)
                    if gr2.allow:
                        if soft_ml_gates:
                            final_long = True
                            reject_tail = "gates_passed_long"
                        else:
                            g5 = apply_gate5_min_edge(proba, thr, self._v43_gate_state)
                            final_long = bool(g5.allow)
                            if not final_long:
                                reject_tail = g5.reject_reason or "min_edge_cost"
                else:
                    reject_tail = gr2.reject_reason or "gate"
            elif raw_short:
                gr2s = apply_post_threshold_gates_short(
                    raw_short=raw_short,
                    regime=regime,
                    current_bar_index=bar_idx,
                    has_open_position=has_open,
                    state=self._v43_gate_state,
                )
                reject_tail = gr2s.reject_reason or "below_threshold_short"
                if gr2s.allow:
                    if (
                        bool(getattr(settings, "jacksparrow_v43_state_heads_enabled", False))
                        and not soft_ml_gates
                    ):
                        gu = apply_uncertainty_gate(
                            uncertainty_score, self._v43_gate_state
                        )
                        if not gu.allow:
                            reject_tail = gu.reject_reason or "high_uncertainty"
                            gr2s = V43GateResult(allow=False, reject_reason=reject_tail)
                    if gr2s.allow:
                        if soft_ml_gates:
                            final_short = True
                            reject_tail = "gates_passed_short"
                        else:
                            g5s = apply_gate5_min_edge_short(
                                proba, short_thr, self._v43_gate_state
                            )
                            final_short = bool(g5s.allow)
                            if not final_short:
                                reject_tail = g5s.reject_reason or "min_edge_cost"
                else:
                    reject_tail = gr2s.reject_reason or "gate"
            else:
                if proba <= (thr - max(0.0, eps_eff)):
                    reject_tail = "below_threshold"
                elif eps_eff > 0.0 and proba <= thr:
                    reject_tail = "near_threshold"
                elif short_enabled and proba >= -short_thr:
                    reject_tail = "below_threshold_short"
                else:
                    reject_tail = "below_threshold"

            collapse_rate = self._v43_gate_state.counters.collapse_rate()
            self._v43_gate_state.record_collapse_sample(collapse_rate)
            score_std = float(features_dict.get("returns_std_20", 0.0) or 0.0)
            epsilon_bump = maybe_widen_epsilon_on_high_collapse(
                self._v43_gate_state,
                score_std=score_std,
            )
            if epsilon_bump is not None:
                logger.warning(
                    "high_collapse_rate_alert",
                    symbol=symbol,
                    collapse_rate=collapse_rate,
                    rolling_collapse_rate=self._v43_gate_state.rolling_collapse_rate(),
                    epsilon_bump=epsilon_bump,
                )
            await self._persist_v43_gate_state_locked(symbol)

        gate_reject = None if (final_long or final_short) else reject_tail
        apply_gates_to_ml_validation(
            ml_validation,
            final_long=final_long,
            final_short=final_short,
            gate_reject=gate_reject,
        )
        ml_validation.target_horizon_bars = exec_bars
        ml_validation.horizon_minutes = horizon_minutes
        ml_validation.multi_horizon_evidence = mh_evidence.to_dict()

        strat_side = (
            "LONG"
            if strategy_candidate.direction == "LONG"
            else ("SHORT" if strategy_candidate.direction == "SHORT" else "FLAT")
        )
        ml_confirms = (
            ml_confirms_direction(ml_validation, strat_side, eps=eps, require_gated=True)
            if strat_side != "FLAT"
            else False
        )
        ml_gates_passed = bool(final_long or final_short)
        trade_score = score_trade_setup(
            strategy=strategy_candidate,
            ml_validation=ml_validation,
            structure=structure,
            ml_confirms=ml_confirms,
        )

        ml_sig, ml_conf, ml_size = ml_candidate_signal_from_validation(
            ml_validation, prefer_gated=True
        )

        max_pct = float(getattr(settings, "jacksparrow_v43_max_position_pct", 0.2) or 0.2)
        pos_hint = float(max(0.01, min(1.0, max_pct * u_scale)))

        head_summary = " ".join(
            f"{k}={h.direction}"
            for k, h in sorted(mh_evidence.heads.items())
        )
        evidence_lines = [
            f"expected_return={proba:.5f} thr={thr:.5f} eps={eps:.5f} regime={regime}",
            f"ml_gate_horizon_bars={training_forward_bars} exec_bars={exec_bars} ({horizon_minutes}m)",
            f"multi_head={head_summary} align={mh_evidence.alignment_score:.2f}",
            f"thesis={strategy_candidate.signal} type={strategy_candidate.thesis_type} "
            f"thesis_horizon_bars={strategy_candidate.intended_horizon_bars}",
            f"ml_confirms={ml_confirms} gates final_long={final_long} final_short={final_short}",
            f"trade_score={trade_score.score:.1f} passed={trade_score.passed}",
            f"collapse_rate={self._v43_gate_state.counters.collapse_rate():.3f}",
        ]
        v43_decision = {
            "enabled": True,
            "conclusion": "HOLD - strategy-first adjudication pending policy",
            "confidence": float(pred0.confidence),
            "evidence": evidence_lines,
            "final_long": final_long,
            "final_short": final_short,
            "ml_confirms_long": ml_validation.confirms_long,
            "ml_confirms_short": ml_validation.confirms_short,
            "ml_candidate_signal": ml_sig,
            "position_size_hint": 0.0,
            "strategy_signal": strategy_candidate.signal,
            "trade_score": trade_score.score,
            "target_horizon_bars": exec_bars,
            "horizon_minutes": horizon_minutes,
            "multi_horizon_evidence": mh_evidence.to_dict(),
        }

        ts = datetime.now(timezone.utc)
        feat_list = [
            MCPFeature(
                name=str(k),
                version="1.0.0",
                value=float(v),
                timestamp=ts,
                quality=FeatureQuality.HIGH,
                metadata={"v43": True},
                computation_time_ms=0.0,
            )
            for k, v in sorted(closed_feats.items())[:80]
        ]
        if not feat_list:
            feat_list = [
                MCPFeature(
                    name="v43_placeholder",
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

        model_predictions_payload: List[Dict[str, Any]] = [
            self._serialize_model_prediction(p) for p in model_response.predictions
        ]

        market_context_for_reasoning: Dict[str, Any] = {
            **(context or {}),
            "symbol": symbol,
            "features": features_dict,
            "model_predictions": model_predictions_payload,
            "consensus_signal": model_response.consensus_prediction,
            "consensus_confidence": model_response.consensus_confidence,
            "feature_quality": feature_response.overall_quality.value,
            "quality_score": feature_response.quality_score,
            "v43_dedicated_decision": v43_decision,
            "v43_gate_reject": gate_reject,
            "v43_closed_bar_index": bar_idx,
            "v43_training_forward_bars": training_forward_bars,
            "v43_execution_horizon_bars": exec_bars,
            "v43_horizon_minutes": horizon_minutes,
            "v43_execution_profile": v43_execution_profile,
            "multi_horizon_evidence": mh_evidence.to_dict(),
            "v43_bundle_metadata": bundle_metadata,
            "ml_validation": ml_validation.to_dict(),
            "strategy_candidate": strategy_candidate.to_dict(),
            "thesis_verdict": thesis_verdict_to_dict(thesis_verdict),
            "hypothesis_snapshot": mctx.get("hypothesis_snapshot"),
            "environment_scores": mctx.get("environment_scores"),
            "market_structure": structure.to_dict(),
            "trade_score": trade_score.to_dict(),
            "regime": regime,
            "v43_regime": regime,
            "p_regime_favorable": p_regime_favorable,
            "p_setup_quality": p_setup_quality,
            "p_vol_expansion": p_vol_expansion,
            "uncertainty_score": uncertainty_score,
        }
        if isinstance(mctx.get("market_intelligence"), dict):
            market_context_for_reasoning["market_intelligence"] = mctx["market_intelligence"]
            market_context_for_reasoning["market_regime"] = mctx["market_intelligence"].get(
                "regime", regime
            )

        evidence_bundle = build_evidence_bundle(
            market_context=market_context_for_reasoning,
            ml_validation=ml_validation,
            structure=structure,
            strategy=strategy_candidate,
            thesis_verdict=thesis_verdict,
            ml_confirms=ml_confirms,
        )
        market_forecast = market_forecast_from_context(
            market_context_for_reasoning, ml_validation
        )
        market_context_for_reasoning["evidence_bundle"] = evidence_bundle.to_dict()
        market_context_for_reasoning["market_forecast"] = market_forecast.to_dict()

        if bool(getattr(settings, "evidence_graph_enabled", True)):
            from agent.intelligence.evidence_graph import build_evidence_graph

            evidence_graph = build_evidence_graph(
                evidence_bundle,
                direction=strategy_candidate.signal,
                market_forecast=market_forecast.to_dict(),
            )
            market_context_for_reasoning["evidence_graph"] = evidence_graph.to_dict()

        if bool(getattr(settings, "market_intelligence_enabled", True)):
            from agent.intelligence.market_state_engine import market_state_engine

            ms_traj = market_state_engine.update_from_cycle(
                symbol=symbol,
                bar_index=bar_idx,
                regime=regime,
                evidence=evidence_bundle,
                forecast=market_forecast,
                breakout_failed=reject_tail in ("failed_breakout", "breakout_failed"),
            )
            market_context_for_reasoning["market_state_trajectory"] = ms_traj.to_dict()

        ml_evidence = MLEvidenceSnapshot(
            symbol=symbol,
            source="v43_orchestrator",
            ml_candidate_signal=ml_sig,
            ml_candidate_confidence=ml_conf,
            ml_candidate_position_size=ml_size,
            consensus_signal=float(model_response.consensus_prediction),
            consensus_confidence=float(model_response.consensus_confidence),
            model_predictions=model_predictions_payload,
            v43_gate_reject=gate_reject,
            v43_regime=regime,
            market_context_excerpt={
                "v43_dedicated_decision": v43_decision,
                "v43_execution_profile": v43_execution_profile,
                "v43_training_forward_bars": training_forward_bars,
                "v43_execution_horizon_bars": exec_bars,
                "multi_horizon_evidence": mh_evidence.to_dict(),
                "ml_validation": ml_validation.to_dict(),
                "strategy_candidate": strategy_candidate.to_dict(),
                "trade_score": trade_score.to_dict(),
                "p_regime_favorable": p_regime_favorable,
                "p_setup_quality": p_setup_quality,
                "p_vol_expansion": p_vol_expansion,
                "uncertainty_score": uncertainty_score,
            },
            thesis_signal=strategy_candidate.signal,
            trade_score=trade_score.score,
            ml_confirms=ml_gates_passed or ml_confirms,
            p_regime_favorable=float(p_regime_favorable)
            if p_regime_favorable is not None
            else None,
            p_setup_quality=float(p_setup_quality) if p_setup_quality is not None else None,
            p_vol_expansion=float(p_vol_expansion) if p_vol_expansion is not None else None,
            uncertainty_score=(
                float(uncertainty_score) if uncertainty_score is not None else None
            ),
        )

        from agent.core.portfolio_intelligence import (
            apply_portfolio_guard_to_verdict,
            evaluate_portfolio_guard,
            fetch_portfolio_exposure_snapshot,
        )

        portfolio_snap = await fetch_portfolio_exposure_snapshot(
            symbol,
            market_context_for_reasoning,
        )
        market_context_for_reasoning["portfolio_exposure"] = portfolio_snap.to_dict()
        _eq = float(portfolio_snap.portfolio_equity_usd or 0.0)
        _notional = float(portfolio_snap.total_open_notional_usd or 0.0)
        market_context_for_reasoning["portfolio_heat"] = (
            _notional / _eq if _eq > 0 else 0.0
        )
        _long_n = float(portfolio_snap.long_notional_usd or 0.0)
        _short_n = float(portfolio_snap.short_notional_usd or 0.0)
        _side_total = _long_n + _short_n
        market_context_for_reasoning["position_correlation"] = (
            max(_long_n, _short_n) / _side_total if _side_total > 0 else 0.0
        )
        market_context_for_reasoning.update(_v43_reasoning_portfolio_risk_overlay(symbol))
        market_context_for_reasoning["regime_bar_age"] = int(
            self._v43_gate_state.regime_bar_age or 0
        )
        thesis_allowed = sum(
            1
            for code in (thesis_verdict.reason_codes or [])
            if str(code).startswith("regime_allows_")
        )
        market_context_for_reasoning["regime_transition_risk"] = compute_regime_transition_risk(
            thesis_allowed
        )

        use_fast_reasoning = (
            bool(getattr(settings, "reasoning_fast_path_on_blocked_entry", False))
            and has_open
            and gate_reject == "open_position"
            and not final_long
            and not final_short
        )
        if use_fast_reasoning:
            reasoning_chain = self._build_fast_hold_reasoning_chain(
                symbol=symbol,
                market_context=market_context_for_reasoning,
                gate_reject=gate_reject,
                model_predictions_payload=model_predictions_payload,
            )
        else:
            reasoning_request = MCPReasoningRequest(
                symbol=symbol,
                market_context=market_context_for_reasoning,
                use_memory=bool(self.vector_store),
            )
            reasoning_chain = await self.reasoning_engine.generate_reasoning(
                reasoning_request
            )

        policy_verdict = agent_policy_engine.evaluate(
            ml_evidence=ml_evidence,
            conclusion=reasoning_chain.conclusion or "",
            market_context=market_context_for_reasoning,
            reasoning_chain=reasoning_chain,
        )
        policy_verdict = self._maybe_apply_rule_based_pipeline(
            symbol=symbol,
            bar_idx=bar_idx,
            features_dict=features_dict,
            regime=regime,
            structure=structure,
            thesis_verdict=thesis_verdict,
            has_open=has_open,
            contract_state=contract_state,
            market_context=market_context_for_reasoning,
            policy_verdict=policy_verdict,
            pos_hint=pos_hint,
            df_feat=mctx.get("df_feat_pre"),
        )
        market_context_for_reasoning["policy_verdict"] = policy_verdict.model_dump(
            mode="json"
        )

        _entry_signals = ENTRY_SIGNALS
        _dominant_type: Optional[str] = None
        _hyp_raw = market_context_for_reasoning.get("hypothesis_snapshot")
        if isinstance(_hyp_raw, dict):
            _dom = _hyp_raw.get("dominant")
            if isinstance(_dom, dict):
                _dominant_type = str(_dom.get("thesis_type") or "") or None

        from agent.intelligence.rule_based_pipeline import is_rule_based_mode, should_enforce_fsm
        from agent.core.evidence_types import ConvictionResult
        from agent.core.signal_vocabulary import is_entry_signal as _is_entry

        rb_ctx = market_context_for_reasoning.get("rule_based_pipeline")
        use_structural_conviction = (
            isinstance(rb_ctx, dict)
            and (is_rule_based_mode() or should_enforce_fsm())
        )
        if use_structural_conviction:
            conf = float(rb_ctx.get("structural_confidence") or 0.5)
            size_frac = float(rb_ctx.get("position_size_fraction") or 0.0)
            sig = str(policy_verdict.signal or "HOLD")
            below = conf < float(getattr(settings, "conviction_entry_floor", 0.35) or 0.35)
            conviction_result = ConvictionResult(
                conviction=conf,
                direction=sig if _is_entry(sig) else None,
                size_fraction=0.0 if below or not _is_entry(sig) else size_frac,
                dimensions={"structural": conf},
                reason_codes=[f"structural_conviction={conf:.3f}"],
                below_entry_floor=below,
            )
        else:
            conviction_result = compute_conviction(
                evidence_bundle,
                policy_verdict.signal,
                dominant_thesis_type=_dominant_type,
            )
        market_context_for_reasoning["conviction"] = conviction_result.to_dict()

        if evidence_based_sizing_enabled() and policy_verdict.signal in _entry_signals:
            if conviction_result.below_entry_floor:
                policy_verdict = PolicyVerdict(
                    signal="HOLD",
                    confidence=policy_verdict.confidence,
                    position_size=0.0,
                    reason_codes=list(policy_verdict.reason_codes)
                    + ["no_edge"]
                    + list(conviction_result.reason_codes),
                    ml_evidence_id=policy_verdict.ml_evidence_id,
                    adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
                    memory_size_scale=policy_verdict.memory_size_scale,
                    conviction=conviction_result.conviction,
                    size_fraction=0.0,
                    evidence=evidence_bundle.to_dict(),
                    abstention="NO_EDGE",
                )
            else:
                base_size = float(policy_verdict.position_size or 0.0)
                if base_size <= 0:
                    base_size = float(pos_hint)
                sized = base_size * conviction_result.size_fraction
                policy_verdict = PolicyVerdict(
                    signal=policy_verdict.signal,
                    confidence=policy_verdict.confidence,
                    position_size=sized,
                    reason_codes=list(policy_verdict.reason_codes)
                    + list(conviction_result.reason_codes),
                    ml_evidence_id=policy_verdict.ml_evidence_id,
                    adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
                    memory_size_scale=policy_verdict.memory_size_scale,
                    conviction=conviction_result.conviction,
                    size_fraction=conviction_result.size_fraction,
                    evidence=evidence_bundle.to_dict(),
                )
        elif policy_verdict.signal in _entry_signals:
            policy_verdict = PolicyVerdict(
                signal=policy_verdict.signal,
                confidence=policy_verdict.confidence,
                position_size=policy_verdict.position_size,
                reason_codes=list(policy_verdict.reason_codes),
                ml_evidence_id=policy_verdict.ml_evidence_id,
                adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
                memory_size_scale=policy_verdict.memory_size_scale,
                conviction=conviction_result.conviction,
                size_fraction=conviction_result.size_fraction,
                evidence=evidence_bundle.to_dict(),
            )

        logger.info(
            "evidence_conviction_cycle",
            symbol=symbol,
            conviction=conviction_result.conviction,
            size_fraction=conviction_result.size_fraction,
            below_entry_floor=conviction_result.below_entry_floor,
            policy_signal=policy_verdict.signal,
            evidence_scores=evidence_bundle.scores,
            hard_block_reason=gate_reject,
        )
        if bool(getattr(settings, "evidence_shadow_dual_pipeline", True)):
            from agent.core.conviction import confluence_score_to_size_multiplier

            legacy_mult = confluence_score_to_size_multiplier(float(trade_score.score))
            logger.info(
                "evidence_shadow_dual_pipeline",
                symbol=symbol,
                legacy_trade_score=float(trade_score.score),
                legacy_size_multiplier=legacy_mult,
                evidence_conviction=conviction_result.conviction,
                evidence_size_fraction=conviction_result.size_fraction,
            )

        portfolio_guard = evaluate_portfolio_guard(
            portfolio_snap,
            symbol=symbol,
            proposed_signal=policy_verdict.signal,
            proposed_size_fraction=float(policy_verdict.position_size or 0.0),
        )
        pre_guard_signal = policy_verdict.signal
        pre_guard_size = float(policy_verdict.position_size or 0.0)
        policy_verdict = apply_portfolio_guard_to_verdict(
            policy_verdict,
            portfolio_guard,
            symbol=symbol,
        )
        market_context_for_reasoning["portfolio_guard"] = portfolio_guard.to_dict()
        logger.info(
            "portfolio_guard_evaluated",
            symbol=symbol,
            pre_signal=pre_guard_signal,
            post_signal=policy_verdict.signal,
            pre_size=pre_guard_size,
            post_size=float(policy_verdict.position_size or 0.0),
            guard_action=portfolio_guard.action,
            heat_ratio=portfolio_guard.heat_ratio,
            side_concentration=portfolio_guard.side_concentration_ratio,
            shadow_only=portfolio_guard.shadow_only,
            reason_codes=portfolio_guard.reason_codes,
        )

        abstention = abstention_from_reason_codes(
            policy_verdict.reason_codes,
            gate_reject=gate_reject,
            signal=policy_verdict.signal,
        )
        if abstention and not policy_verdict.abstention:
            policy_verdict = PolicyVerdict(
                signal=policy_verdict.signal,
                confidence=policy_verdict.confidence,
                position_size=policy_verdict.position_size,
                reason_codes=list(policy_verdict.reason_codes),
                ml_evidence_id=policy_verdict.ml_evidence_id,
                adopted_ml_candidate=policy_verdict.adopted_ml_candidate,
                memory_size_scale=policy_verdict.memory_size_scale,
                conviction=policy_verdict.conviction,
                size_fraction=policy_verdict.size_fraction,
                evidence=policy_verdict.evidence,
                abstention=abstention,
            )

        if trade_score_hard_veto_enabled():
            _gated_adopt_codes = frozenset(
                {
                    "fusion_ml_gated_thesis_neutral",
                    "fusion_ml_or_thesis_gated_neutral",
                    "fusion_ml_or_thesis_ml",
                }
            )
            score_min = float(getattr(settings, "agent_trade_score_min", 35.0) or 35.0)
            if any(c in _gated_adopt_codes for c in (policy_verdict.reason_codes or [])):
                score_min = min(
                    score_min,
                    float(
                        getattr(settings, "agent_trade_score_min_gated_ml_adoption", 30.0)
                        or 30.0
                    ),
                )
            score_ok = trade_score.passed or (
                float(trade_score.score) >= score_min and (final_long or final_short)
            )
            if policy_verdict.signal in _entry_signals and not score_ok:
                policy_verdict = PolicyVerdict(
                    signal="HOLD",
                    confidence=policy_verdict.confidence,
                    position_size=0.0,
                    reason_codes=list(policy_verdict.reason_codes)
                    + ["trade_score_below_min", f"score={trade_score.score:.1f}"],
                    ml_evidence_id=policy_verdict.ml_evidence_id,
                    adopted_ml_candidate=False,
                    conviction=policy_verdict.conviction,
                    size_fraction=0.0,
                    evidence=policy_verdict.evidence,
                )

        policy_entry = policy_verdict.signal in _entry_signals
        v43_exec = {
            "enabled": True,
            "skip_legacy_entry_gate": True,
            "skip_volatility_requirement": True,
            "margin_cap_fraction": pos_hint if policy_entry else 0.0,
            "unc_scale": u_scale,
            "desired_side": signal_to_position_side(policy_verdict.signal),
        }
        market_context_for_reasoning["v43_execution_profile"] = v43_exec
        if policy_entry:
            v43_decision["conclusion"] = (
                f"{policy_verdict.signal} - strategy-first (thesis+ML policy)"
            )
            v43_decision["position_size_hint"] = float(policy_verdict.position_size or pos_hint)
            v43_decision["policy_signal"] = policy_verdict.signal
            # Gate truth stays in final_long/final_short from ml_validation; do not overwrite.

        policy_decision = {
            "signal": policy_verdict.signal,
            "position_size": float(policy_verdict.position_size or 0.0),
            "confidence": float(policy_verdict.confidence or 0.0),
            "reasoning": reasoning_chain.conclusion,
            "policy_reason_codes": list(policy_verdict.reason_codes),
        }

        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "features": {
                "data": [{"name": f.name, "value": f.value, "quality": f.quality.value}
                       for f in feature_response.features],
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
            "market_context": market_context_for_reasoning,
            "reasoning": {
                "chain_id": reasoning_chain.chain_id,
                "steps": [
                    {
                        "step_number": step.step_number,
                        "step_name": step.step_name,
                        "description": step.description,
                        "evidence": step.evidence,
                        "confidence": step.confidence,
                        "timestamp": step.timestamp.isoformat(),
                    }
                    for step in reasoning_chain.steps
                ],
                "conclusion": reasoning_chain.conclusion,
                "final_confidence": reasoning_chain.final_confidence,
                "signal_strength": getattr(reasoning_chain, "signal_strength", None),
            },
            "decision": policy_decision,
            "policy_verdict": policy_verdict.model_dump(mode="json"),
            "ml_evidence_snapshot": ml_evidence.model_dump(mode="json"),
        }
        result["inference_latency_ms"] = (time.perf_counter() - _t0) * 1000.0
        _gc = self._v43_gate_state.counters
        logger.info(
            "mcp_orchestrator_v43_prediction_complete",
            symbol=symbol,
            policy_signal=policy_verdict.signal,
            thesis_signal=strategy_candidate.signal,
            trade_score=trade_score.score,
            final_long=final_long,
            final_short=final_short,
            reject=reject_tail,
            proba=proba,
            thr=thr,
            eps=eps,
            v43_collapse_rate=_gc.collapse_rate(),
            v43_cnt_signals_raw=_gc.signals_raw,
            v43_cnt_rejected_pos_open=_gc.rejected_pos_open,
            v43_cnt_rejected_debounce=_gc.rejected_debounce,
            v43_cnt_rejected_freq_cap=_gc.rejected_freq_cap,
            v43_cnt_rejected_regime=_gc.rejected_regime,
            v43_cnt_rejected_edge=_gc.rejected_edge,
            v43_cnt_trades_executed=_gc.trades_executed,
        )
        try:
            from agent.core.signal_recovery_telemetry import (
                check_over_gating_regression,
                record_decision_cycle,
            )

            record_decision_cycle(
                symbol=symbol,
                signal=str(policy_verdict.signal),
                confidence=float(policy_verdict.confidence),
                expected_return=float(proba),
                trade_score=float(trade_score.score),
                thesis_signal=str(strategy_candidate.signal),
                policy_reason_codes=list(policy_verdict.reason_codes),
                v43_collapse_rate=float(_gc.collapse_rate()),
                proba=float(proba),
                threshold=float(thr),
                inference_stack=str(
                    getattr(settings, "jacksparrow_v43_inference_stack", "meta_calibrator")
                ),
                event="v43_prediction_complete",
                extra={
                    "final_long": final_long,
                    "final_short": final_short,
                    "reject": reject_tail,
                },
            )
            check_over_gating_regression()
        except Exception:
            pass
        return result

    async def _process_rule_based_prediction(
        self,
        symbol: str,
        context: Dict[str, Any],
        _t0: float,
    ) -> Dict[str, Any]:
        """ML-free path: features → Understanding → Narrative → Gates → FSM."""
        from agent.core.agent_thesis_engine import (
            agent_thesis_engine,
            thesis_verdict_to_dict,
        )
        from agent.core.market_structure import classify_market_structure
        from agent.core.reasoning_engine import ReasoningStep
        from agent.data.incremental_feature_engine import incremental_feature_engine
        from agent.data.market_data_manager import MarketDataManager
        from agent.intelligence.ic_node import build_closed_feats_from_v43_dataframes
        from agent.intelligence.regime_classifier import classify_regime
        from agent.intelligence.rule_based_pipeline import rule_based_pipeline
        from agent.intelligence.market_understanding_engine import features_history_from_matrix
        from agent.events.schemas import PolicyVerdict, MLEvidenceSnapshot

        if not self.delta_client:
            return self._create_empty_prediction_response(
                symbol, context, reason="delta_client_unavailable"
            )

        context = _merge_prediction_context_with_agent_state(symbol, context)
        manager = self.market_data_manager
        if isinstance(manager, MarketDataManager):
            bundle = await manager.get_v43_frames(symbol)
            df5, df15, df1h, df_fund, df_oi, df_mark = (
                bundle.df5m,
                bundle.df15m,
                bundle.df1h,
                bundle.df_funding,
                bundle.df_oi,
                bundle.df_mark,
            )
        else:
            from agent.core.v43_market_frames import fetch_v43_market_frames

            df5, df15, df1h, df_fund, df_oi, df_mark = await fetch_v43_market_frames(
                self.delta_client, symbol
            )

        if df5.empty or len(df5) < V43_MIN_5M_ROWS:
            return self._create_empty_prediction_response(
                symbol,
                context,
                reason=f"insufficient_5m_rows:{len(df5) if not df5.empty else 0}",
            )

        import pandas as pd

        from agent.core.v43_contract_state import get_contract_state

        ticker_row: Dict[str, Any] = {}
        if isinstance(df_oi, pd.DataFrame) and not df_oi.empty:
            ticker_row = df_oi.iloc[-1].to_dict()
        contract_state = await get_contract_state(symbol, ticker_row=ticker_row)

        try:
            closed_feats, _df_feat = await asyncio.to_thread(
                incremental_feature_engine.update_from_frames,
                symbol,
                df5,
                df15,
                df1h,
                df_fund,
                df_oi=df_oi,
                df_mark=df_mark,
            )
        except ValueError:
            closed_feats, _df_feat = await asyncio.to_thread(
                build_closed_feats_from_v43_dataframes,
                df5,
                df15,
                df1h,
                df_fund,
                df_oi=df_oi,
                df_mark=df_mark,
            )

        has_open = bool(context.get("has_open_position", False))
        if not has_open:
            has_open = await _exchange_has_open_position_async(symbol)

        regime = classify_regime(closed_feats)
        features_dict = {str(k): float(v) for k, v in closed_feats.items()}
        structure = classify_market_structure(
            features_dict,
            v43_regime=regime,
            contract_state=contract_state,
        )
        thesis_mc: Dict[str, Any] = {
            **(context or {}),
            "symbol": symbol,
            "features": features_dict,
            "regime": regime,
            "market_structure": structure.to_dict(),
            "has_open_position": has_open,
            "v43_contract_state": contract_state,
        }
        thesis_verdict = agent_thesis_engine.evaluate(regime, thesis_mc)
        bar_idx = int(closed_5m_bar_index(df5))

        rb = rule_based_pipeline.run_cycle(
            symbol=symbol,
            bar_index=bar_idx,
            features=features_dict,
            regime=regime,
            thesis_signal=str(thesis_verdict.signal),
            thesis_type=str(thesis_verdict.thesis_type),
            has_open_position=has_open,
            structure=structure,
            gate_state=self._v43_gate_state,
            contract_state=contract_state,
            features_history=features_history_from_matrix(_df_feat),
        )

        pos_hint = float(getattr(settings, "default_position_size_fraction", 0.05) or 0.05)
        fsm_sig = rb.fsm_decision.entry_signal
        from agent.core.signal_vocabulary import is_entry_signal

        reasons: List[str] = []
        if is_entry_signal(fsm_sig) and rb.structural_gates.trade_allowed:
            reasons.append("rule_based_fsm_entry")
            signal = fsm_sig
            size = pos_hint * float(rb.position_size_fraction or 0.5)
        else:
            signal = "HOLD"
            size = 0.0
            reasons.append(rb.fsm_decision.abstention_reason or "fsm_hold")

        policy_verdict = PolicyVerdict(
            signal=signal,
            confidence=float(rb.structural_confidence),
            position_size=size,
            reason_codes=reasons,
            adopted_ml_candidate=False,
            conviction=rb.structural_confidence,
            size_fraction=rb.position_size_fraction,
        )

        market_context: Dict[str, Any] = {
            **context,
            "symbol": symbol,
            "features": features_dict,
            "regime": regime,
            "thesis_verdict": thesis_verdict_to_dict(thesis_verdict),
            "market_structure": structure.to_dict(),
            "rule_based_pipeline": rb.to_dict(),
            "market_state": rb.market_state.to_dict(),
            "narrative_tail": rb.narrative_tail,
            "structural_gates": rb.structural_gates.to_dict(),
            "fsm_state": rb.fsm_decision.fsm_state,
            "entry_signal": rb.fsm_decision.entry_signal,
            "thesis_health": rb.fsm_decision.thesis_health,
            "position_lifecycle": rb.fsm_decision.position_lifecycle,
            "policy_verdict": policy_verdict.model_dump(mode="json"),
            "decision_engine_mode": "rule_based",
        }

        conclusion = (
            f"{signal} — rule-based FSM ({rb.fsm_decision.fsm_state}) "
            f"setup={rb.structural_gates.setup_type}"
        )
        chain_id = f"rb_{symbol}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        step = ReasoningStep(
            step_number=1,
            step_name="rule_based_pipeline",
            description="Market Understanding → Narrative → Gates → FSM",
            evidence=[conclusion],
            confidence=float(rb.structural_confidence),
            timestamp=datetime.now(timezone.utc),
        )

        ml_evidence = MLEvidenceSnapshot(
            symbol=symbol,
            source="rule_based_pipeline",
            ml_candidate_signal=signal,
            ml_candidate_confidence=float(rb.structural_confidence),
            ml_candidate_position_size=size,
            thesis_signal=str(thesis_verdict.signal),
        )

        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "features": {"data": [], "count": 0},
            "models": {"predictions": [], "consensus_prediction": 0.0, "consensus_confidence": 0.0},
            "model_predictions": [],
            "market_context": market_context,
            "reasoning": {
                "chain_id": chain_id,
                "steps": [
                    {
                        "step_number": step.step_number,
                        "step_name": step.step_name,
                        "description": step.description,
                        "evidence": step.evidence,
                        "confidence": step.confidence,
                        "timestamp": step.timestamp.isoformat(),
                    }
                ],
                "conclusion": conclusion,
                "final_confidence": float(rb.structural_confidence),
            },
            "decision": {
                "signal": signal,
                "position_size": size,
                "confidence": float(rb.structural_confidence),
                "reasoning": conclusion,
                "policy_reason_codes": reasons,
            },
            "policy_verdict": policy_verdict.model_dump(mode="json"),
            "ml_evidence_snapshot": ml_evidence.model_dump(mode="json"),
        }
        result["inference_latency_ms"] = (time.perf_counter() - _t0) * 1000.0
        logger.info(
            "mcp_orchestrator_rule_based_prediction_complete",
            symbol=symbol,
            signal=signal,
            fsm_state=rb.fsm_decision.fsm_state,
            trade_allowed=rb.structural_gates.trade_allowed,
            setup_type=rb.structural_gates.setup_type,
        )
        return result

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
            if self._prediction_lock.locked():
                logger.info(
                    "mcp_orchestrator_prediction_skipped_in_flight",
                    symbol=symbol,
                    context_keys=list(context.keys()) if context else None,
                    message="Another v43 prediction is running; skipping duplicate trigger",
                )
                return self._create_empty_prediction_response(
                    symbol,
                    context or {},
                    reason="prediction_skipped_in_flight",
                )

            async with self._prediction_lock:
                logger.info(
                    "mcp_orchestrator_prediction_start",
                    symbol=symbol,
                    context_keys=list(context.keys()) if context else None,
                )

                context = context or {}

                from agent.intelligence.rule_based_pipeline import is_rule_based_mode

                if is_rule_based_mode():
                    return await self._process_rule_based_prediction(symbol, context, _t0)

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

                return await self._process_jacksparrow_v43_prediction(symbol, context, _t0)

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

    async def generate_reasoning(
        self,
        symbol: str,
        market_context: Optional[Dict[str, Any]] = None,
        use_memory: bool = False
    ) -> MCPReasoningChain:
        """
        Generate reasoning chain for trading decision.

        This is a wrapper method that delegates to the reasoning engine.

        Args:
            symbol: Trading symbol (e.g., "BTCUSD")
            market_context: Market context for reasoning
            use_memory: Whether to use memory for context

        Returns:
            MCPReasoningChain with 6-step reasoning process
        """
        if not self._initialized:
            raise RuntimeError("MCP Orchestrator not initialized")

        if not self.reasoning_engine:
            raise RuntimeError("Reasoning engine not initialized")

        request = MCPReasoningRequest(
            symbol=symbol,
            market_context=market_context or {},
            use_memory=use_memory
        )

        logger.debug("mcp_orchestrator_generating_reasoning",
                    symbol=symbol,
                    use_memory=use_memory)

        return await self.reasoning_engine.generate_reasoning(request)

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

    def _build_fast_hold_reasoning_chain(
        self,
        *,
        symbol: str,
        market_context: Dict[str, Any],
        gate_reject: Optional[str],
        model_predictions_payload: List[Dict[str, Any]],
    ) -> MCPReasoningChain:
        """Lightweight reasoning when entry blocked by open_position (PERF-03)."""
        from agent.core.reasoning_engine import ReasoningStep

        ts = datetime.now(timezone.utc)
        desc = (
            f"HOLD - fast path: open position blocks new entry "
            f"(gate_reject={gate_reject or 'open_position'})"
        )
        step = ReasoningStep(
            step_number=1,
            step_name="Fast Hold",
            description=desc,
            evidence=[f"symbol={symbol}", f"gate_reject={gate_reject}"],
            confidence=0.0,
            timestamp=ts,
        )
        return MCPReasoningChain(
            chain_id=str(uuid.uuid4()),
            timestamp=ts,
            market_context=market_context,
            steps=[step],
            conclusion=desc,
            final_confidence=0.0,
            model_predictions=list(model_predictions_payload or []),
            feature_context=[],
            signal_strength=None,
        )
        
    def _extract_decision_from_reasoning(self, reasoning_chain: MCPReasoningChain) -> Dict[str, Any]:
        """Extract trading decision from reasoning chain conclusion."""
        conclusion = (reasoning_chain.conclusion or "").strip()
        token = normalize_signal(conclusion.upper().split()[0].rstrip(":-,") if conclusion else "HOLD")

        default_size = float(getattr(settings, "max_position_size", 0.1) or 0.1)
        if token == "STRONG_LONG":
            signal = "STRONG_LONG"
            position_size = default_size
        elif token == "LONG":
            signal = "LONG"
            position_size = max(0.01, default_size * 0.5)
        elif token == "STRONG_SHORT":
            signal = "STRONG_SHORT"
            position_size = default_size
        elif token == "SHORT":
            signal = "SHORT"
            position_size = max(0.01, default_size * 0.5)
        else:
            signal = "HOLD"
            position_size = 0.0
        
        return {
            "signal": signal,
            "position_size": position_size,
            "confidence": reasoning_chain.final_confidence,
            "reasoning": reasoning_chain.conclusion
        }

    def _create_empty_prediction_response(
        self,
        symbol: str,
        context: Dict[str, Any],
        *,
        reason: str = "unknown",
        **log_fields: Any,
    ) -> Dict[str, Any]:
        """Create explicit error response when no features are available.

        This intentionally does NOT fabricate a neutral HOLD decision. Instead it
        returns an error payload that callers must treat as \"no decision\".
        """
        logger.warning(
            "mcp_orchestrator_prediction_no_features",
            symbol=symbol,
            reason=reason,
            trigger=(context or {}).get("trigger"),
            **log_fields,
        )
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
            "success": False,
            "error_code": "NO_FEATURES",
            "error": "No features available for prediction",
            "failure_reason": reason,
            "request_context": dict(context or {}),
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
            "request_context": dict(context or {}),
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
            return "LONG"
        if value < -0.3:
            return "SHORT"
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

    async def _enrich_decision_event_self_awareness(
        self,
        decision_event: DecisionReadyEvent,
        *,
        symbol: str,
        signal: str,
        confidence: float,
        verdict: PolicyVerdict,
        ml_evidence: MLEvidenceSnapshot,
        market_context: Dict[str, Any],
        chain_id: str,
        timestamp: datetime,
        decision_for_store: Dict[str, Any],
        market_context_for_store: Dict[str, Any],
    ) -> None:
        """Attach introspection + memory ids to DecisionReady payload before publish."""
        payload = decision_event.payload
        payload["decision_event_id"] = decision_event.event_id
        payload["server_timestamp_ms"] = int(time.time() * 1000)

        memory_context_id = await self._store_decision_context(
            symbol=symbol,
            decision=decision_for_store,
            market_context=market_context_for_store,
            chain_id=chain_id,
            timestamp=timestamp,
            decision_event_id=decision_event.event_id,
        )
        if memory_context_id:
            payload["memory_context_id"] = memory_context_id

        if getattr(settings, "agent_introspection_enabled", True):
            mem_count = await self._memory_context_count()
            intro = build_introspection_snapshot(
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                policy_reason_codes=list(verdict.reason_codes),
                policy_verdict=verdict.model_dump(mode="json"),
                ml_evidence_snapshot=ml_evidence.model_dump(mode="json"),
                market_context=market_context,
                trade_score=ml_evidence.trade_score,
                memory_enabled=bool(self.vector_store),
                memory_context_count=mem_count,
            )
            payload["agent_introspection"] = intro.to_dict()

    async def _store_decision_context(
        self,
        symbol: str,
        decision: Dict[str, Any],
        market_context: Dict[str, Any],
        chain_id: str,
        timestamp: datetime,
        decision_event_id: Optional[str] = None,
    ) -> Optional[str]:
        """Store a decision context in the vector store for future similarity search."""
        if not self.vector_store:
            return None
        try:
            dec = dict(decision)
            if decision_event_id:
                dec["decision_event_id"] = decision_event_id
            ctx = self._build_decision_context_for_storage(
                symbol=symbol,
                decision=dec,
                market_context=market_context,
                chain_id=chain_id,
                timestamp=timestamp,
            )
            if ctx:
                if decision_event_id:
                    ctx.decision_event_id = decision_event_id
                await self.vector_store.store_decision_context(ctx)
                logger.debug(
                    "mcp_orchestrator_decision_context_stored",
                    context_id=ctx.context_id,
                    symbol=symbol,
                )
                return ctx.context_id
        except Exception as e:
            logger.warning(
                "mcp_orchestrator_decision_context_store_failed",
                symbol=symbol,
                error=str(e),
            )
        return None

    async def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive health status of all MCP components."""
        health_status = {
            "mcp_orchestrator": {
                "status": "healthy" if self._initialized else "unhealthy",
                "initialized": self._initialized,
                "components": {}
            }
        }

        try:
            if self.feature_server:
                feature_health = await asyncio.wait_for(
                    self.feature_server.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have a status field
                if "status" not in feature_health:
                    feature_health["status"] = "up" if feature_health.get("feature_registry_count", 0) > 0 else "unknown"
                health_status["mcp_orchestrator"]["components"]["feature_server"] = feature_health
            else:
                health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": "Feature server not initialized"}
        except asyncio.TimeoutError:
            logger.warning("feature_server_health_timeout")
            health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("feature_server_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["feature_server"] = {"status": "unknown", "error": str(e)}

        try:
            if self.model_registry:
                model_health = await asyncio.wait_for(
                    self.model_registry.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have required fields
                if "status" not in model_health:
                    total_models = model_health.get("total_models", 0)
                    healthy_models = model_health.get("healthy_models", 0)
                    model_health["status"] = "up" if total_models > 0 and healthy_models > 0 else "unknown"
                health_status["mcp_orchestrator"]["components"]["model_registry"] = model_health
            else:
                health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": "Model registry not initialized"}
        except asyncio.TimeoutError:
            logger.warning("model_registry_health_timeout")
            health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("model_registry_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["model_registry"] = {"status": "unknown", "error": str(e)}

        try:
            if self.reasoning_engine:
                reasoning_health = await asyncio.wait_for(
                    self.reasoning_engine.get_health_status(),
                    timeout=1.0  # 1 second timeout per component
                )
                # Ensure we have a status field
                if "status" not in reasoning_health:
                    reasoning_health["status"] = "up"
                health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = reasoning_health
            else:
                health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": "Reasoning engine not initialized"}
        except asyncio.TimeoutError:
            logger.warning("reasoning_engine_health_timeout")
            health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": "Health check timeout"}
        except Exception as e:
            logger.error("reasoning_engine_health_failed", error=str(e), exc_info=True)
            health_status["mcp_orchestrator"]["components"]["reasoning_engine"] = {"status": "unknown", "error": str(e)}

        try:
            from agent.intelligence.market_intelligence_store import market_intelligence_store

            intel_health = market_intelligence_store.get_health_summary(
                symbol=getattr(settings, "trading_symbol", None)
                or getattr(settings, "agent_symbol", None)
            )
            health_status["mcp_orchestrator"]["components"]["market_intelligence"] = intel_health
        except Exception as e:
            health_status["mcp_orchestrator"]["components"]["market_intelligence"] = {
                "status": "unknown",
                "error": str(e),
            }

        if isinstance(self.market_data_manager, object) and self.market_data_manager is not None:
            mgr = self.market_data_manager
            mgr_health: Dict[str, Any] = {"status": "up"}
            if hasattr(mgr, "get_health"):
                try:
                    mgr_health = mgr.get_health()
                except Exception as e:
                    mgr_health = {"status": "unknown", "error": str(e)}
            health_status["mcp_orchestrator"]["components"]["market_data_manager"] = mgr_health

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
        """Handle prediction request event."""
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            context = payload.get("context", {})

            result = await self.process_prediction_request(symbol, context)

            # Emit completion event (even on error, so subscribers can see error state)
            completion_event = ModelPredictionCompleteEvent(
                source="mcp_orchestrator",
                correlation_id=event.event_id,
                payload=result
            )
            await event_bus.publish(completion_event)

            # Do not broadcast error fallback as main trading signal – skip DecisionReadyEvent
            # when result is an error response (synthetic HOLD 0%) so UI keeps last good signal.
            if result.get("error") is not None:
                return

            ctx = context if isinstance(context, dict) else {}
            if ctx.get("dry_run") or str(ctx.get("trigger") or "") == "model_health_warmup":
                logger.info(
                    "mcp_orchestrator_decision_ready_skipped_non_tradable",
                    symbol=symbol,
                    trigger=ctx.get("trigger"),
                    dry_run=bool(ctx.get("dry_run")),
                    correlation_id=event.event_id,
                )
                return

            # When a full decision is available from process_prediction_request,
            # emit a DecisionReadyEvent directly so downstream consumers
            # (backend/websocket/front-end) receive signals even if intermediate
            # handlers are misaligned with the payload structure.
            decision = result.get("decision") or {}
            if isinstance(decision, dict) and decision.get("signal") is not None:
                reasoning = result.get("reasoning") or {}
                decision_symbol = result.get("symbol") or symbol
                timestamp = result.get("timestamp") or datetime.now(timezone.utc)

                pv_raw = result.get("policy_verdict")
                if isinstance(pv_raw, dict) and pv_raw.get("signal"):
                    verdict = PolicyVerdict(**pv_raw)
                    ml_evidence = build_ml_evidence_from_orchestrator_result(result)
                else:
                    ml_evidence = build_ml_evidence_from_orchestrator_result(result)
                    verdict = agent_policy_engine.evaluate(
                        ml_evidence=ml_evidence,
                        conclusion=str(reasoning.get("conclusion") or ""),
                        market_context=result.get("market_context")
                        if isinstance(result.get("market_context"), dict)
                        else {},
                    )

                signal = verdict.signal
                position_size = verdict.position_size
                confidence = verdict.confidence

                _entry_signals = ENTRY_SIGNALS
                mctx = result.get("market_context") if isinstance(result.get("market_context"), dict) else {}
                v43_bar = mctx.get("v43_closed_bar_index")
                bar_i_hold_skip: Optional[int] = None
                if v43_bar is not None:
                    try:
                        bar_i_hold_skip = int(v43_bar)
                    except (TypeError, ValueError):
                        bar_i_hold_skip = None
                if (
                    signal == "HOLD"
                    and bar_i_hold_skip is not None
                    and self._v43_last_entry_decision_bar == bar_i_hold_skip
                ):
                    logger.info(
                        "v43_decision_emit_skipped_hold_same_bar",
                        symbol=decision_symbol,
                        bar_idx=bar_i_hold_skip,
                        correlation_id=event.event_id,
                    )
                    return
                if signal in _entry_signals and v43_bar is not None:
                    try:
                        bar_i = int(v43_bar)
                    except (TypeError, ValueError):
                        bar_i = None
                    if bar_i is not None and self._v43_last_entry_decision_bar == bar_i:
                        logger.info(
                            "v43_decision_emit_skipped_duplicate_bar",
                            symbol=decision_symbol,
                            signal=signal,
                            bar_idx=bar_i,
                            correlation_id=event.event_id,
                        )
                        return
                    if bar_i is not None:
                        self._v43_last_entry_decision_bar = bar_i

                # Normalize per-model predictions so backend and frontend can
                # consistently build model_consensus and reasoning views.
                raw_model_predictions = result.get("model_predictions") or result.get("models", {}).get(
                    "predictions", []
                )
                model_predictions_for_reasoning = self._build_model_predictions_for_reasoning(
                    raw_model_predictions
                )

                reasoning_chain_payload: Dict[str, Any] = {
                    "chain_id": reasoning.get("chain_id"),
                    "steps": reasoning.get("steps", []),
                    "conclusion": reasoning.get("conclusion"),
                    "final_confidence": reasoning.get("final_confidence"),
                    "reasoning_confidence_raw": reasoning.get("reasoning_confidence_raw"),
                    "signal_strength": reasoning.get("signal_strength"),
                    "model_predictions": model_predictions_for_reasoning,
                    "market_context": result.get("market_context") or {},
                }
                step7_meta = None
                for st in reasoning.get("steps") or []:
                    if isinstance(st, dict) and st.get("step_number") == 7:
                        step7_meta = st.get("step_metadata")
                        break
                if isinstance(step7_meta, dict) and step7_meta.get("entry_proba_margin_mean") is not None:
                    reasoning_chain_payload["entry_proba_margin_mean"] = step7_meta.get(
                        "entry_proba_margin_mean"
                    )

                strategy_origin = (
                    "agent_thesis_origin" in verdict.reason_codes
                    or "agent_thesis_confirms_ml" in verdict.reason_codes
                )
                ts_val = ml_evidence.trade_score
                ts_detail = None
                if isinstance(mctx, dict):
                    ts_raw = mctx.get("trade_score")
                    if isinstance(ts_raw, dict):
                        ts_detail = ts_raw
                decision_payload = {
                        "symbol": decision_symbol,
                        "signal": signal,
                        "confidence": confidence,
                        "position_size": position_size,
                        "reasoning_chain": reasoning_chain_payload,
                        "timestamp": timestamp,
                        "policy_authority": PolicyAuthority.AGENT_POLICY.value,
                        "policy_reason_codes": list(verdict.reason_codes),
                        "ml_evidence_snapshot": ml_evidence.model_dump(mode="json"),
                        "policy_verdict": verdict.model_dump(mode="json"),
                        "strategy_origin": strategy_origin,
                        "trade_score": ts_val,
                        "trade_score_detail": ts_detail,
                        "thesis_signal": ml_evidence.thesis_signal,
                        "hypothesis_snapshot": (mctx or {}).get("hypothesis_snapshot"),
                        "anticipated_horizon_bars": int(
                            (mctx or {}).get("v43_execution_horizon_bars", 0) or 0
                        )
                        or None,
                        "anticipated_horizon_minutes": int(
                            (mctx or {}).get("v43_horizon_minutes", 0) or 0
                        )
                        or None,
                        "market_state": (mctx or {}).get("market_state"),
                        "narrative_tail": (mctx or {}).get("narrative_tail"),
                        "structural_gates": (mctx or {}).get("structural_gates"),
                        "fsm_state": (mctx or {}).get("fsm_state"),
                        "entry_signal": (mctx or {}).get("entry_signal"),
                        "thesis_health": (mctx or {}).get("thesis_health"),
                        "position_lifecycle": (mctx or {}).get("position_lifecycle"),
                }
                decision_payload.update(_decision_ws_metadata(result))
                _enrich_confidence_semantics(decision_payload)

                decision_event = DecisionReadyEvent(
                    source="agent_policy_engine",
                    correlation_id=event.event_id,
                    payload=decision_payload,
                )

                await self._enrich_decision_event_self_awareness(
                    decision_event,
                    symbol=decision_symbol,
                    signal=signal,
                    confidence=float(confidence) if confidence is not None else 0.0,
                    verdict=verdict,
                    ml_evidence=ml_evidence,
                    market_context=mctx,
                    chain_id=str(reasoning.get("chain_id", "unknown")),
                    timestamp=timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc),
                    decision_for_store={
                        "signal": signal,
                        "confidence": confidence,
                        "position_size": position_size,
                    },
                    market_context_for_store=reasoning_chain_payload.get("market_context", {}),
                )

                await event_bus.publish(decision_event)

                self._schedule_prediction_audit(
                    correlation_id=event.event_id,
                    symbol=decision_symbol,
                    confidence=float(confidence) if confidence is not None else None,
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
                try:
                    from agent.core.signal_recovery_telemetry import record_decision_cycle

                    _hyp_extra: Dict[str, Any] = {"event_id": decision_event.event_id}
                    _hyp_raw = (mctx or {}).get("hypothesis_snapshot")
                    if isinstance(_hyp_raw, dict):
                        _dom = _hyp_raw.get("dominant")
                        if isinstance(_dom, dict) and _dom.get("id"):
                            _hyp_extra["hypothesis_dominant"] = str(_dom["id"])
                        if _hyp_raw.get("aggregate_confidence") is not None:
                            _hyp_extra["aggregate_confidence"] = float(
                                _hyp_raw["aggregate_confidence"]
                            )
                        if _hyp_raw.get("hypothesis_margin") is not None:
                            _hyp_extra["hypothesis_margin"] = float(
                                _hyp_raw["hypothesis_margin"]
                            )
                    record_decision_cycle(
                        symbol=decision_symbol,
                        signal=str(signal),
                        confidence=float(confidence) if confidence is not None else 0.0,
                        trade_score=float(ts_val) if ts_val is not None else None,
                        thesis_signal=str(ml_evidence.thesis_signal)
                        if ml_evidence.thesis_signal
                        else None,
                        hypothesis_dominant=_hyp_extra.get("hypothesis_dominant"),
                        aggregate_confidence=_hyp_extra.get("aggregate_confidence"),
                        hypothesis_margin=_hyp_extra.get("hypothesis_margin"),
                        policy_reason_codes=list(verdict.reason_codes),
                        event="decision_ready_emitted",
                        extra=_hyp_extra,
                    )
                except Exception:
                    pass

        except Exception as e:
            logger.error("mcp_orchestrator_prediction_request_failed",
                        event_id=event.event_id,
                        error=str(e),
                        exc_info=True)

    async def _persist_v43_gate_state_locked(self, symbol: str) -> None:
        """Persist gate state (caller must hold ``_v43_gate_state_lock``)."""
        sym = str(symbol or self._v43_gate_symbol or "").upper()
        if not sym:
            return
        try:
            from agent.core.redis_config import get_redis

            redis_client = await get_redis()
            await persist_gate_state(sym, self._v43_gate_state, redis_client)
        except Exception as e:
            logger.warning("v43_gate_state_persist_failed", symbol=sym, error=str(e))

    def record_v43_signal_decision(self, bar_index: int) -> None:
        """Stamp v43 debounce after a gated BUY/SELL signal (before fill)."""
        self._v43_gate_state.note_signal_decision(int(bar_index))

    def rollback_v43_signal_decision(self, bar_index: Optional[int] = None) -> None:
        """Roll back debounce when execution fails after policy entry."""
        self._v43_gate_state.note_entry_failed(bar_index)

    def record_v43_trade_executed(self, bar_index: int) -> None:
        """Stamp v43 frequency + debounce state after a fill."""
        bar_i = int(bar_index)
        self._v43_gate_state.note_signal_decision(bar_i)
        self._v43_gate_state.note_entry(bar_i, datetime.now(timezone.utc))
        self._v43_gate_state.counters.trades_executed += 1

    async def persist_v43_gate_state_after_trade(self, symbol: str) -> None:
        """Persist gate counters after fill (async-safe)."""
        async with self._v43_gate_state_lock:
            await self._persist_v43_gate_state_locked(symbol)


# Create global MCP orchestrator instance
mcp_orchestrator = MCPOrchestrator()