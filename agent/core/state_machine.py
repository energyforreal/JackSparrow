"""
Agent state machine.

Manages agent state transitions and state-specific behavior.
Event-driven state transitions.
"""

from enum import Enum
from typing import Optional, Callable, Dict, Any, List
from datetime import datetime, timezone
import asyncio
import structlog

from agent.core.config import settings

from agent.events.event_bus import event_bus
from agent.events.schemas import (
    CandleClosedEvent,
    ReasoningCompleteEvent,
    RiskApprovedEvent,
    OrderFillEvent,
    RiskAlertEvent,
    EmergencyStopEvent,
    PositionClosedEvent,
    StateTransitionEvent,
    DecisionReadyEvent,
    ModelPredictionCompleteEvent,
    EventType,
)
from agent.core.learning_system import TradeOutcome

logger = structlog.get_logger()


class AgentState(Enum):
    """Agent state enumeration."""
    
    INITIALIZING = "INITIALIZING"
    OBSERVING = "OBSERVING"
    THINKING = "THINKING"
    DELIBERATING = "DELIBERATING"
    ANALYZING = "ANALYZING"
    EXECUTING = "EXECUTING"
    MONITORING_POSITION = "MONITORING_POSITION"
    DEGRADED = "DEGRADED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class StateTransition:
    """State transition definition."""
    
    def __init__(
        self,
        from_state: AgentState,
        to_state: AgentState,
        condition: Callable[[Dict[str, Any]], bool],
        reason: str = ""
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.reason = reason


class AgentStateMachine:
    """Agent state machine manager."""
    
    def __init__(self, context_manager, learning_system=None, model_registry=None):
        """Initialize state machine."""
        self.current_state = AgentState.INITIALIZING
        self.previous_state: Optional[AgentState] = None
        self.state_entry_time = datetime.now(timezone.utc)
        self.transitions: Dict[AgentState, List[StateTransition]] = {}
        self.state_handlers: Dict[AgentState, Callable] = {}
        self.context_manager = context_manager
        self.learning_system = learning_system
        self.model_registry = model_registry

        # Initialize transitions
        self._initialize_transitions()
    
    async def initialize(self):
        """Initialize state machine and register event handlers."""
        event_bus.subscribe(EventType.CANDLE_CLOSED, self._handle_candle_closed)
        event_bus.subscribe(EventType.REASONING_COMPLETE, self._handle_reasoning_complete)
        event_bus.subscribe(EventType.DECISION_READY, self._handle_decision_ready)
        event_bus.subscribe(
            EventType.MODEL_PREDICTION_COMPLETE, self._handle_prediction_complete
        )
        event_bus.subscribe(EventType.RISK_APPROVED, self._handle_risk_approved)
        event_bus.subscribe(EventType.ORDER_FILL, self._handle_order_fill)
        event_bus.subscribe(EventType.RISK_ALERT, self._handle_risk_alert)
        event_bus.subscribe(EventType.EMERGENCY_STOP, self._handle_emergency_stop)
        event_bus.subscribe(EventType.POSITION_CLOSED, self._handle_position_closed)
    
    async def _handle_candle_closed(self, event: CandleClosedEvent):
        """Handle candle closed event - transition OBSERVING -> THINKING."""
        if self.current_state == AgentState.OBSERVING:
            await self._transition_to(AgentState.THINKING, "Candle closed - analyzing market")
    
    async def _handle_reasoning_complete(self, event: ReasoningCompleteEvent):
        """Handle reasoning complete event - transition THINKING -> DELIBERATING."""
        if self.current_state == AgentState.THINKING:
            await self._transition_to(AgentState.DELIBERATING, "Reasoning chain complete")
    
    async def _handle_decision_ready(self, event: DecisionReadyEvent):
        """Handle decision ready: return to OBSERVING on HOLD, else await risk."""
        signal = str(event.payload.get("signal", "") or "")
        if self.current_state == AgentState.THINKING:
            if signal == "HOLD":
                await self._transition_to(
                    AgentState.OBSERVING,
                    "HOLD decision - returning to observation mode",
                )
            else:
                await self._transition_to(
                    AgentState.DELIBERATING,
                    "Trade signal - awaiting risk approval",
                )
            return
        if self.current_state == AgentState.DELIBERATING:
            if signal == "HOLD":
                await self._transition_to(
                    AgentState.OBSERVING,
                    "HOLD decision - returning to observation mode",
                )
            # For BUY/SELL signals, stay in DELIBERATING to wait for risk approval

    async def _handle_prediction_complete(self, event: ModelPredictionCompleteEvent):
        """Recover from THINKING when the candle-close prediction fails without DECISION_READY."""
        if self.current_state != AgentState.THINKING:
            return
        payload = event.payload if isinstance(event.payload, dict) else {}
        if not payload.get("error"):
            return
        req_ctx = payload.get("request_context") or {}
        trigger = str(req_ctx.get("trigger") or "")
        if trigger not in ("candle_closed", "staleness_watchdog"):
            logger.debug(
                "state_machine_prediction_error_ignored",
                trigger=trigger or None,
                error_code=payload.get("error_code"),
                message="Only candle/staleness prediction errors recover THINKING",
            )
            return
        await self._transition_to(
            AgentState.OBSERVING,
            "Prediction failed - resuming observation",
        )
    
    async def _handle_risk_approved(self, event: RiskApprovedEvent):
        """Handle risk approved event - transition DELIBERATING/ANALYZING -> EXECUTING."""
        if self.current_state in [AgentState.DELIBERATING, AgentState.ANALYZING]:
            await self._transition_to(AgentState.EXECUTING, "Risk approved - executing trade")
    
    async def _handle_order_fill(self, event: OrderFillEvent):
        """Handle order fill event - transition EXECUTING -> MONITORING_POSITION."""
        if self.current_state == AgentState.EXECUTING:
            await self._transition_to(AgentState.MONITORING_POSITION, "Order filled - monitoring position")
    
    async def _handle_risk_alert(self, event: RiskAlertEvent):
        """Handle risk alert event - transition to DEGRADED."""
        if event.payload.get("severity") == "CRITICAL":
            await self._transition_to(AgentState.DEGRADED, f"Risk alert: {event.payload.get('message')}")
    
    async def _handle_emergency_stop(self, event: EmergencyStopEvent):
        """Handle emergency stop event - transition to EMERGENCY_STOP."""
        await self._transition_to(AgentState.EMERGENCY_STOP, f"Emergency stop: {event.payload.get('reason')}")
    
    async def _handle_position_closed(self, event: PositionClosedEvent):
        """Handle position closed event - transition MONITORING_POSITION -> OBSERVING and record outcome for learning."""
        payload = event.payload
        if self.current_state == AgentState.MONITORING_POSITION:
            exit_reason = payload.get("exit_reason", "unknown")
            await self._transition_to(
                AgentState.OBSERVING,
                f"Position closed - {exit_reason}"
            )
            # Update context to clear position
            await self.context_manager.update_state({
                "position": None,
                "position_opened": False
            })

        try:
            from agent.intelligence.market_fsm import market_fsm
            from agent.intelligence.trade_archetype_memory import trade_archetype_memory

            sym = str(payload.get("symbol") or "")
            pnl_raw = payload.get("pnl_percent", payload.get("pnl", 0))
            try:
                pnl = float(pnl_raw or 0)
            except (TypeError, ValueError):
                pnl = 0.0
            outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
            mc = payload.get("market_context")
            mc = mc if isinstance(mc, dict) else {}
            rb = mc.get("rule_based_pipeline")
            rb = rb if isinstance(rb, dict) else {}
            gates = rb.get("structural_gates") if isinstance(rb.get("structural_gates"), dict) else {}
            mstate = rb.get("market_state") if isinstance(rb.get("market_state"), dict) else {}
            fsm = rb.get("fsm_decision") if isinstance(rb.get("fsm_decision"), dict) else {}
            if sym:
                trade_archetype_memory.record_close(
                    symbol=sym,
                    setup_type=str(gates.get("setup_type") or "unknown"),
                    regime=str(mstate.get("regime") or "neutral"),
                    narrative_tail=list(mc.get("narrative_tail") or rb.get("narrative_tail") or []),
                    gate_snapshot=dict(gates.get("categories") or {}),
                    fsm_path=[str(fsm.get("fsm_state") or "")],
                    outcome=outcome,
                    pnl_pct=pnl,
                )
                market_fsm.on_position_closed(sym)
        except Exception as exc:
            logger.debug("trade_archetype_record_skipped", error=str(exc))

        # Trade outcome feedback loop: record outcome and update model weights
        model_predictions = payload.get("model_predictions")
        if model_predictions is not None and len(model_predictions) > 0 and self.learning_system and self.model_registry:
            try:
                entry_time = payload.get("entry_time")
                exit_time = payload.get("timestamp")
                now = datetime.now(timezone.utc)
                et = entry_time
                xt = exit_time
                if et is not None and getattr(et, "tzinfo", None) is None and hasattr(et, "replace"):
                    et = et.replace(tzinfo=timezone.utc)
                if xt is not None and getattr(xt, "tzinfo", None) is None and hasattr(xt, "replace"):
                    xt = xt.replace(tzinfo=timezone.utc)
                if et is not None and xt is not None:
                    holding_hours = (xt - et).total_seconds() / 3600.0
                else:
                    holding_hours = 0.0
                trade_outcome = TradeOutcome(
                    trade_id=payload.get("position_id", ""),
                    symbol=payload.get("symbol", ""),
                    entry_price=float(payload.get("entry_price", 0)),
                    exit_price=float(payload.get("exit_price", 0)),
                    entry_time=et or now,
                    exit_time=xt or now,
                    position_size=float(payload.get("quantity", 0)),
                    predicted_signal=payload.get("predicted_signal", ""),
                    actual_pnl=float(payload.get("pnl", 0)),
                    holding_period_hours=holding_hours,
                )
                await self.learning_system.record_trade_outcome(trade_outcome, model_predictions)
                model_names = list(self.model_registry.models.keys()) if self.model_registry.models else []
                n = max(1, len(model_names))
                current_weights = {
                    m: self.model_registry.model_weights.get(m, 1.0 / n)
                    for m in model_names
                }
                if not current_weights and model_names:
                    current_weights = {m: 1.0 / len(model_names) for m in model_names}
                updated_weights = await self.learning_system.get_updated_model_weights(current_weights)
                if updated_weights:
                    self.model_registry.update_weights_from_performance(updated_weights)
            except Exception as e:
                logger.warning(
                    "position_closed_learning_failed",
                    error=str(e),
                    exc_info=True,
                )

        reflection = payload.get("reflection_snapshot")
        if (
            isinstance(reflection, dict)
            and self.learning_system
            and getattr(settings, "agent_reflection_policy_feedback_enabled", False)
        ):
            try:
                await self.learning_system.record_reflection_outcome(
                    reflection,
                    model_predictions if isinstance(model_predictions, list) else None,
                )
            except Exception as e:
                logger.warning(
                    "position_closed_reflection_learning_failed",
                    error=str(e),
                    exc_info=True,
                )

        if getattr(settings, "entry_quality_learning_enabled", False):
            try:
                from agent.intelligence.post_trade_analyzer import analyze_post_trade
                from agent.core.entry_quality import apply_dimension_calibration_feedback
                from agent.persistence.trade_snapshot import merge_close_fields

                entry_snap = payload.get("entry_decision_snapshot") or {}
                if isinstance(entry_snap, dict) and entry_snap:
                    merged = merge_close_fields(entry_snap, payload)
                    analysis = analyze_post_trade(merged)
                    dc_eq = {}
                    if isinstance(entry_snap.get("decision_context"), dict):
                        dc_eq = entry_snap["decision_context"].get("entry_quality") or {}
                    eq_at_entry = dc_eq if isinstance(dc_eq, dict) else {}
                    dims = (
                        eq_at_entry.get("dimensions")
                        if isinstance(eq_at_entry.get("dimensions"), dict)
                        else {}
                    )
                    pnl = float(payload.get("pnl") or payload.get("pnl_usd") or 0.0)
                    shadow = bool(
                        getattr(settings, "entry_quality_learning_shadow_mode", True)
                    )
                    if getattr(settings, "trade_intelligence_learning_enabled", False):
                        shadow = shadow or bool(
                            getattr(
                                settings,
                                "trade_intelligence_learning_shadow_mode",
                                True,
                            )
                        )
                    apply_dimension_calibration_feedback(
                        dims,
                        str(analysis.get("root_cause") or "unknown"),
                        pnl,
                        shadow=shadow,
                    )
            except Exception as e:
                logger.warning(
                    "entry_quality_learning_failed",
                    error=str(e),
                    exc_info=True,
                )

        if getattr(settings, "trade_outcomes_writes_enabled", True):
            try:
                from agent.persistence.db_writes import persist_trade_outcome_async
                from agent.persistence.performance_context import record_position_closed

                pnl_usd = float(payload.get("pnl") or 0)
                record_position_closed(pnl_usd=pnl_usd)

                async def _persist_sql_outcome() -> None:
                    raw_closed = payload.get("timestamp")
                    closed_at = (
                        raw_closed
                        if isinstance(raw_closed, datetime)
                        else datetime.now(timezone.utc)
                    )
                    raw_opened = payload.get("entry_time")
                    opened_at = raw_opened if isinstance(raw_opened, datetime) else None
                    entry = float(payload.get("entry_price") or 0)
                    exitp = float(payload.get("exit_price") or 0)
                    qty = float(payload.get("quantity") or 0)
                    pnl = float(payload.get("pnl") or 0)
                    denom = (entry * qty) if entry and qty else 0.0
                    pnl_pct = (pnl / denom * 100.0) if denom else None
                    merged_meta = payload.get("entry_decision_snapshot")
                    if not isinstance(merged_meta, dict):
                        merged_meta = {
                            "reasoning_chain_id": payload.get("reasoning_chain_id"),
                        }

                    position_id = str(payload.get("position_id") or "")
                    symbol_str = str(payload.get("symbol", ""))

                    if getattr(settings, "trade_mfe_mae_at_close_enabled", False):
                        try:
                            from agent.persistence.trade_excursions import (
                                compute_excursions_for_close,
                            )

                            excursions = await compute_excursions_for_close(
                                symbol=symbol_str,
                                side=str(payload.get("side") or "long"),
                                entry_price=entry,
                                exit_price=exitp,
                                opened_at=opened_at or closed_at,
                                closed_at=closed_at,
                                metadata=merged_meta,
                            )
                            outcome = merged_meta.get("outcome")
                            if not isinstance(outcome, dict):
                                outcome = {}
                                merged_meta["outcome"] = outcome
                            outcome["excursions"] = excursions
                            payload["excursions"] = excursions
                        except Exception as exc_exc:
                            logger.warning(
                                "mfe_mae_at_close_failed",
                                position_id=position_id,
                                error=str(exc_exc),
                            )

                    if getattr(settings, "wallet_ledger_sync_enabled", False):
                        try:
                            from agent.core.execution import execution_module
                            from agent.core.wallet_attribution import WalletAttributionEngine
                            from agent.core.wallet_ledger_service import get_wallet_ledger_service
                            from agent.persistence.db_writes import fetch_wallet_transactions_async
                            from agent.persistence.trade_snapshot import merge_close_fields

                            duration_sec = 3600
                            if opened_at and closed_at:
                                duration_sec = max(
                                    300,
                                    int((closed_at - opened_at).total_seconds()) + 120,
                                )
                            delta_client = getattr(
                                execution_module, "delta_client", None
                            )
                            if delta_client is not None:
                                await get_wallet_ledger_service(
                                    delta_client
                                ).sync_incremental(
                                    transaction_types=str(
                                        getattr(
                                            settings,
                                            "wallet_ledger_default_transaction_types",
                                            "commission,funding",
                                        )
                                    ),
                                    lookback_seconds=duration_sec,
                                    reason="position_closed",
                                )
                            product_id: Optional[int] = None
                            if delta_client is not None and symbol_str:
                                try:
                                    product_id = await delta_client.resolve_product_id(
                                        symbol_str
                                    )
                                except Exception:
                                    product_id = None
                            wallet_rows = await fetch_wallet_transactions_async(
                                settings.database_url,
                                product_id=product_id,
                                from_time=opened_at,
                                to_time=closed_at,
                            )
                            attr = WalletAttributionEngine().attribute_for_position(
                                payload,
                                wallet_rows,
                                product_id=product_id,
                            )
                            payload["wallet_attribution"] = attr.to_dict()
                            if isinstance(merged_meta, dict):
                                merged_meta = merge_close_fields(merged_meta, payload)
                        except Exception as wallet_exc:
                            logger.warning(
                                "wallet_attribution_at_close_failed",
                                position_id=position_id,
                                error=str(wallet_exc),
                            )

                    try:
                        from agent.persistence.decision_events import (
                            decision_event_emitter,
                            extract_denorm_from_metadata,
                        )

                        if position_id and getattr(
                            settings, "trade_decision_events_enabled", False
                        ):
                            if payload.get("excursions"):
                                decision_event_emitter.emit_if_changed(
                                    position_id=position_id,
                                    symbol=symbol_str,
                                    event_type="mfe_mae_computed",
                                    reasoning_chain_id=payload.get("reasoning_chain_id"),
                                    payload={"excursions": payload.get("excursions")},
                                )
                            decision_event_emitter.emit_if_changed(
                                position_id=position_id,
                                symbol=symbol_str,
                                event_type="close_outcome",
                                reasoning_chain_id=payload.get("reasoning_chain_id"),
                                payload={
                                    "pnl": pnl,
                                    "exit_reason": payload.get("exit_reason"),
                                    "exit_price": exitp,
                                },
                            )
                            graph = decision_event_emitter.build_causality_graph(
                                position_id
                            )
                            merged_meta["causality_graph"] = graph
                            merged_meta["decision_event_count"] = graph.get(
                                "event_count", 0
                            )
                            decision_event_emitter.reset_position(position_id)

                        denorm = extract_denorm_from_metadata(merged_meta)
                    except Exception as denorm_exc:
                        logger.warning(
                            "trade_outcome_denorm_failed",
                            error=str(denorm_exc),
                        )
                        denorm = None

                    await persist_trade_outcome_async(
                        settings.database_url,
                        position_id=payload.get("position_id"),
                        symbol=symbol_str,
                        side=payload.get("side"),
                        signal=payload.get("predicted_signal"),
                        entry_price=entry,
                        exit_price=exitp,
                        quantity=qty,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        close_reason=payload.get("exit_reason"),
                        opened_at=opened_at,
                        closed_at=closed_at,
                        metadata=merged_meta,
                        denorm=denorm,
                    )
                    try:
                        from agent.persistence.db_writes import (
                            persist_analytics_rollups_async,
                        )

                        await persist_analytics_rollups_async(
                            settings.database_url,
                            symbol=str(payload.get("symbol", "")),
                            pnl_usd=pnl,
                            closed_at=closed_at,
                            metadata=merged_meta,
                        )
                    except Exception as rollup_exc:
                        logger.warning(
                            "analytics_rollup_schedule_failed",
                            error=str(rollup_exc),
                        )

                asyncio.create_task(_persist_sql_outcome(), name="trade_outcome_write")
            except Exception as e:
                logger.warning("trade_outcome_schedule_failed", error=str(e), exc_info=True)

    async def _transition_to(self, new_state: AgentState, reason: str):
        """Transition to new state and emit event.
        
        Args:
            new_state: New state to transition to
            reason: Reason for transition
        """
        if self.current_state == new_state:
            return
        
        from_state = self.current_state
        self.previous_state = self.current_state
        self.current_state = new_state
        self.state_entry_time = datetime.now(timezone.utc)
        
        # Update context
        await self.context_manager.update_state({"state": new_state})
        self.context_manager.add_state_transition(from_state, new_state, reason)
        
        # Emit state transition event
        transition_event = StateTransitionEvent(
            source="state_machine",
            payload={
                "from_state": from_state.value,
                "to_state": new_state.value,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc)
            }
        )
        
        await event_bus.publish(transition_event)
        
        logger.info(
            "state_transition",
            from_state=from_state.value,
            to_state=new_state.value,
            reason=reason,
            event_id=transition_event.event_id
        )
    
    def _initialize_transitions(self):
        """Initialize state transitions."""
        
        # INITIALIZING -> OBSERVING
        self.add_transition(
            AgentState.INITIALIZING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("initialized", False),
            "Initialization complete"
        )
        
        # OBSERVING -> THINKING
        self.add_transition(
            AgentState.OBSERVING,
            AgentState.THINKING,
            lambda ctx: ctx.get("significant_change", False),
            "Significant market change detected"
        )
        
        # THINKING -> DELIBERATING
        self.add_transition(
            AgentState.THINKING,
            AgentState.DELIBERATING,
            lambda ctx: ctx.get("reasoning_complete", False),
            "Reasoning chain complete"
        )
        
        # DELIBERATING -> ANALYZING
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.ANALYZING,
            lambda ctx: ctx.get("needs_analysis", False),
            "More analysis needed"
        )
        
        # DELIBERATING -> EXECUTING
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.EXECUTING,
            lambda ctx: ctx.get("trade_decision", False) and ctx.get("can_execute", True),
            "Trade decision made"
        )
        
        # DELIBERATING -> OBSERVING (when HOLD decision is made)
        self.add_transition(
            AgentState.DELIBERATING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("decision_signal") == "HOLD",
            "HOLD decision - no trade"
        )
        
        # ANALYZING -> EXECUTING
        self.add_transition(
            AgentState.ANALYZING,
            AgentState.EXECUTING,
            lambda ctx: ctx.get("entry_conditions_met", False),
            "Entry conditions met"
        )
        
        # ANALYZING -> OBSERVING
        self.add_transition(
            AgentState.ANALYZING,
            AgentState.OBSERVING,
            lambda ctx: not ctx.get("entry_conditions_met", False) and ctx.get("analysis_complete", False),
            "No trade opportunity"
        )
        
        # EXECUTING -> MONITORING_POSITION
        self.add_transition(
            AgentState.EXECUTING,
            AgentState.MONITORING_POSITION,
            lambda ctx: ctx.get("position_opened", False),
            "Position opened"
        )
        
        # EXECUTING -> OBSERVING
        self.add_transition(
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("execution_failed", False),
            "Execution failed"
        )
        
        # MONITORING_POSITION -> OBSERVING
        self.add_transition(
            AgentState.MONITORING_POSITION,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("position_closed", False) or ctx.get("position") is None,
            "Position closed"
        )
        
        # DEGRADED -> OBSERVING
        self.add_transition(
            AgentState.DEGRADED,
            AgentState.OBSERVING,
            lambda ctx: ctx.get("services_restored", False),
            "Services restored"
        )
        
        # Any -> EMERGENCY_STOP
        for state in AgentState:
            if state != AgentState.EMERGENCY_STOP:
                self.add_transition(
                    state,
                    AgentState.EMERGENCY_STOP,
                    lambda ctx: ctx.get("emergency", False),
                    "Emergency stop triggered"
                )
        
        # EMERGENCY_STOP -> INITIALIZING (manual reset)
        self.add_transition(
            AgentState.EMERGENCY_STOP,
            AgentState.INITIALIZING,
            lambda ctx: ctx.get("manual_reset", False),
            "Manual reset"
        )
    
    def add_transition(
        self,
        from_state: AgentState,
        to_state: AgentState,
        condition: Callable[[Dict[str, Any]], bool],
        reason: str = ""
    ):
        """Add state transition."""
        if from_state not in self.transitions:
            self.transitions[from_state] = []
        
        transition = StateTransition(from_state, to_state, condition, reason)
        self.transitions[from_state].append(transition)
    
    def can_transition(self, context: Dict[str, Any]) -> Optional[AgentState]:
        """Check if state transition is possible."""
        
        if self.current_state not in self.transitions:
            return None
        
        for transition in self.transitions[self.current_state]:
            if transition.condition(context):
                return transition.to_state
        
        return None
    
    def transition_to(self, new_state: AgentState, context: Dict[str, Any]) -> bool:
        """Transition to new state."""
        
        # Check if transition is valid
        possible_state = self.can_transition(context)
        if possible_state == new_state:
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.now(timezone.utc)
            return True
        
        # Allow direct transition to EMERGENCY_STOP from any state
        if new_state == AgentState.EMERGENCY_STOP:
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.now(timezone.utc)
            return True
        
        # Allow manual transitions in development (can be restricted)
        if context.get("manual_transition", False):
            self.previous_state = self.current_state
            self.current_state = new_state
            self.state_entry_time = datetime.now(timezone.utc)
            return True
        
        return False
    
    def get_state_info(self) -> Dict[str, Any]:
        """Get current state information."""
        return {
            "current_state": self.current_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "state_entry_time": self.state_entry_time.isoformat(),
            "time_in_state_seconds": (datetime.now(timezone.utc) - self.state_entry_time).total_seconds()
        }
    
    def is_operational(self) -> bool:
        """Check if agent is in operational state."""
        operational_states = [
            AgentState.OBSERVING,
            AgentState.THINKING,
            AgentState.DELIBERATING,
            AgentState.ANALYZING,
            AgentState.EXECUTING,
            AgentState.MONITORING_POSITION
        ]
        return self.current_state in operational_states
    
    def can_trade(self) -> bool:
        """Check if agent can execute trades."""
        tradeable_states = [
            AgentState.ANALYZING,
            AgentState.EXECUTING
        ]
        return self.current_state in tradeable_states and not self.current_state == AgentState.EMERGENCY_STOP