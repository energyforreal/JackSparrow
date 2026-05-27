"""
MCP Reasoning Engine.

Implements 6-step reasoning chain for trading decisions.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict
import asyncio
import statistics
import time
import uuid

from agent.data.feature_server import MCPFeatureServer, MCPFeatureResponse
from agent.models.mcp_model_registry import (
    MCPModelRegistry,
    MCPModelResponse,
    NoHealthyModelPredictionsError,
)
from agent.memory.vector_store import VectorMemoryStore
from agent.events.event_bus import event_bus
from agent.events.schemas import ReasoningRequestEvent, ReasoningCompleteEvent, DecisionReadyEvent
from agent.core.config import settings
from agent.core.mtf_decision_engine import synthesize_mtf_trading_decision
from agent.learning.dynamic_thresholds import apply_redis_hold_band_overrides
import structlog

logger = structlog.get_logger()


class ReasoningStep(BaseModel):
    """Single step in reasoning chain."""
    step_number: int
    step_name: str
    description: str
    evidence: List[str]
    confidence: float
    timestamp: datetime
    # Optional metadata fields
    data_freshness_seconds: Optional[int] = None
    similarity_score: Optional[float] = None
    feature_quality_score: Optional[float] = None
    step_metadata: Optional[Dict[str, Any]] = None


class MCPReasoningChain(BaseModel):
    """MCP Reasoning Chain structure."""
    model_config = ConfigDict(protected_namespaces=())
    chain_id: str
    timestamp: datetime
    market_context: Dict[str, Any]
    steps: List[ReasoningStep]
    conclusion: str
    final_confidence: float
    model_predictions: List[Dict[str, Any]]
    feature_context: List[Dict[str, Any]]


class MCPReasoningRequest(BaseModel):
    """MCP Reasoning Protocol request."""
    symbol: str
    market_context: Dict[str, Any]
    use_memory: bool = True


class MCPReasoningEngine:
    """MCP Reasoning Engine implementing 6-step reasoning chain."""
    
    def __init__(
        self,
        feature_server: MCPFeatureServer,
        model_registry: MCPModelRegistry,
        vector_store: Optional[VectorMemoryStore] = None,
        learning_system: Optional[Any] = None,
    ):
        """Initialize reasoning engine."""
        self.feature_server = feature_server
        self.model_registry = model_registry
        self.vector_store = vector_store
        self.learning_system = learning_system

    @staticmethod
    def _compute_data_freshness_seconds(market_timestamp: Any) -> Optional[int]:
        """Return age in seconds for a timestamp, handling naive/aware values safely."""
        if not market_timestamp:
            return None
        try:
            if isinstance(market_timestamp, str):
                market_time = datetime.fromisoformat(market_timestamp.replace("Z", "+00:00"))
            elif isinstance(market_timestamp, datetime):
                market_time = market_timestamp
            else:
                return None

            if market_time.tzinfo is None:
                market_time = market_time.replace(tzinfo=timezone.utc)
            return int(
                (
                    datetime.now(timezone.utc)
                    - market_time.astimezone(timezone.utc)
                ).total_seconds()
            )
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _get_model_predictions(market_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Resolve model predictions from canonical or legacy market_context keys."""
        preds = market_context.get("model_predictions")
        if preds is None:
            preds = market_context.get("predictions")
        return preds if isinstance(preds, list) else []

    @staticmethod
    def _normalize_market_context_predictions(
        market_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Ensure ``model_predictions`` is populated for downstream reasoning steps."""
        normalized = dict(market_context or {})
        preds = MCPReasoningEngine._get_model_predictions(normalized)
        if preds:
            normalized["model_predictions"] = preds
        return normalized

    @staticmethod
    def _resolve_decision_step_for_hold(
        request: MCPReasoningRequest,
        steps: List[ReasoningStep],
    ) -> Optional[ReasoningStep]:
        """Return the step whose description reflects the final trade decision."""
        if isinstance(request.market_context.get("strategy_candidate"), dict):
            return next((s for s in steps if s.step_number == 6), None)
        return next((s for s in steps if s.step_number == 5), None)

    @staticmethod
    def _extract_hold_bucket(conclusion: str, evidence: List[str]) -> str:
        """Map free-text HOLD outcomes to a stable diagnostics bucket."""
        text = f"{conclusion} {' '.join(evidence or [])}".lower()
        if "dead zone" in text:
            return "mtf_dead_zone"
        if "below entry edge" in text or "edge below minimum" in text:
            return "mtf_entry_edge"
        if "probability gap below minimum" in text:
            return "mtf_probability_gap"
        if "trend neutral" in text or "trend timeframe neutral" in text:
            return "mtf_trend_neutral"
        if "not confirming trend" in text:
            return "mtf_not_confirming_trend"
        if "trend proba below thresholds" in text:
            return "mtf_trend_probability_threshold"
        if "trend prob diff below edge" in text:
            return "mtf_trend_prob_edge"
        if "entry confidence below minimum" in text:
            return "mtf_entry_confidence_gate"
        if "below rolling percentile" in text:
            return "mtf_strength_percentile"
        if "filter conflicts" in text:
            return "mtf_filter_conflict"
        if "consensus_in_hold_band" in text:
            return "consensus_in_hold_band"
        if "mixed signals" in text:
            return "mixed_signals"
        return "other_hold"

    @staticmethod
    def _summarize_entry_probabilities(
        model_predictions: List[Dict[str, Any]],
    ) -> Dict[str, Optional[float]]:
        """Aggregate buy/sell probability signals for diagnostics logs."""
        buy_vals: List[float] = []
        sell_vals: List[float] = []
        hints_long: List[float] = []
        hints_short: List[float] = []
        for pred in model_predictions or []:
            if not isinstance(pred, dict):
                continue
            ctx = pred.get("context") if isinstance(pred.get("context"), dict) else {}
            entry_proba = ctx.get("entry_proba")
            if isinstance(entry_proba, dict):
                try:
                    buy_vals.append(float(entry_proba.get("buy", 0.0)))
                    sell_vals.append(float(entry_proba.get("sell", 0.0)))
                except (TypeError, ValueError):
                    pass
            for key, bucket in (
                ("RECOMMENDED_LONG_THRESHOLD", hints_long),
                ("RECOMMENDED_SHORT_THRESHOLD", hints_short),
            ):
                raw = ctx.get(key)
                if raw is None:
                    continue
                try:
                    bucket.append(float(raw))
                except (TypeError, ValueError):
                    continue
        return {
            "entry_proba_buy_mean": (sum(buy_vals) / len(buy_vals)) if buy_vals else None,
            "entry_proba_sell_mean": (sum(sell_vals) / len(sell_vals)) if sell_vals else None,
            "entry_proba_models": float(len(buy_vals)) if buy_vals else 0.0,
            "recommended_long_threshold_median": (
                statistics.median(hints_long) if hints_long else None
            ),
            "recommended_short_threshold_median": (
                statistics.median(hints_short) if hints_short else None
            ),
        }
    
    async def initialize(self):
        """Initialize reasoning engine."""
        if self.vector_store:
            await self.vector_store.initialize()
        # ReasoningRequestEvent is handled exclusively by MCPOrchestrator to avoid
        # duplicate reasoning passes and duplicate DecisionReadyEvent emissions.
        # See agent/core/mcp_orchestrator.py::_handle_reasoning_request.
    
    async def shutdown(self):
        """Shutdown reasoning engine."""
        if self.vector_store:
            await self.vector_store.shutdown()
    
    async def _handle_reasoning_request_event(self, event: ReasoningRequestEvent):
        """Deprecated: REASONING_REQUEST is handled by MCPOrchestrator only."""
        logger.warning(
            "reasoning_request_event_unexpected",
            event_id=event.event_id,
            message="ReasoningRequest should be processed by mcp_orchestrator; ignoring.",
        )
    
    async def _emit_reasoning_complete_event(self, request_event: ReasoningRequestEvent, reasoning_chain: MCPReasoningChain):
        """Emit reasoning complete event.
        
        Args:
            request_event: Original reasoning request event
            reasoning_chain: Generated reasoning chain
        """
        try:
            event = ReasoningCompleteEvent(
                source="reasoning_engine",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": reasoning_chain.market_context.get("symbol", request_event.payload.get("symbol")),
                    "reasoning_chain": {
                        "chain_id": reasoning_chain.chain_id,
                        "steps": [step.model_dump() for step in reasoning_chain.steps],
                        "conclusion": reasoning_chain.conclusion,
                        "market_context": reasoning_chain.market_context
                    },
                    "final_confidence": reasoning_chain.final_confidence,
                    "timestamp": reasoning_chain.timestamp
                }
            )
            
            await event_bus.publish(event)
            
            logger.info(
                "reasoning_complete_event_emitted",
                symbol=request_event.payload.get("symbol"),
                chain_id=reasoning_chain.chain_id,
                final_confidence=reasoning_chain.final_confidence,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "reasoning_complete_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def _emit_decision_ready_event(self, request_event: ReasoningRequestEvent, reasoning_chain: MCPReasoningChain):
        """Emit decision ready event.
        
        Args:
            request_event: Original reasoning request event
            reasoning_chain: Generated reasoning chain
        """
        try:
            # Defensive check: ensure model_predictions are present before
            # emitting any trading decision.
            prediction_count = len(reasoning_chain.model_predictions or [])
            if prediction_count == 0:
                logger.error(
                    "decision_ready_event_skipped_no_model_predictions",
                    symbol=reasoning_chain.market_context.get(
                        "symbol", request_event.payload.get("symbol")
                    ),
                    message="Skipping DecisionReadyEvent because reasoning_chain.model_predictions is empty.",
                )
                return

            # Extract signal from conclusion
            conclusion = reasoning_chain.conclusion
            mc = (
                reasoning_chain.market_context
                if isinstance(reasoning_chain.market_context, dict)
                else {}
            )
            v43_dec = mc.get("v43_dedicated_decision") if isinstance(mc, dict) else None
            position_size = 0.0
            if isinstance(v43_dec, dict) and v43_dec.get("enabled"):
                hint = v43_dec.get("position_size_hint")
                if hint is not None:
                    try:
                        position_size = float(hint)
                    except (TypeError, ValueError):
                        position_size = 0.0
            if "STRONG_BUY" in conclusion:
                signal = "STRONG_BUY"
                if position_size <= 0.0:
                    position_size = 0.1  # Max position size
            elif "BUY" in conclusion:
                signal = "BUY"
                if position_size <= 0.0:
                    position_size = 0.05
            elif "STRONG_SELL" in conclusion:
                signal = "STRONG_SELL"
                if position_size <= 0.0:
                    position_size = 0.1
            elif "SELL" in conclusion:
                signal = "SELL"
                if position_size <= 0.0:
                    position_size = 0.05
            else:
                signal = "HOLD"
                position_size = 0.0
            
            event = DecisionReadyEvent(
                source="reasoning_engine",
                correlation_id=request_event.event_id,
                payload={
                    "symbol": reasoning_chain.market_context.get("symbol", request_event.payload.get("symbol")),
                    "signal": signal,
                    "confidence": reasoning_chain.final_confidence,
                    "position_size": position_size,
                    "reasoning_chain": {
                        "chain_id": reasoning_chain.chain_id,
                        "steps": [step.model_dump() for step in reasoning_chain.steps],
                        "conclusion": reasoning_chain.conclusion,
                        "market_context": reasoning_chain.market_context,
                        "model_predictions": reasoning_chain.model_predictions
                    },
                    "timestamp": reasoning_chain.timestamp
                }
            )
            
            await event_bus.publish(event)

            proba_diag = self._summarize_entry_probabilities(
                reasoning_chain.model_predictions or []
            )
            threshold_used = None
            if signal in ("BUY", "STRONG_BUY"):
                threshold_used = proba_diag.get("recommended_long_threshold_median")
            elif signal in ("SELL", "STRONG_SELL"):
                threshold_used = proba_diag.get("recommended_short_threshold_median")
            else:
                threshold_used = max(
                    float(getattr(settings, "min_confidence_threshold", 0.52) or 0.52),
                    0.0,
                )
            logger.info(
                "ml_signal_evaluated",
                symbol=request_event.payload.get("symbol"),
                signal=signal,
                decision=reasoning_chain.conclusion,
                confidence=reasoning_chain.final_confidence,
                threshold_used=threshold_used,
                **proba_diag,
            )
            
            logger.info(
                "decision_ready_event_emitted",
                symbol=request_event.payload.get("symbol"),
                signal=signal,
                confidence=reasoning_chain.final_confidence,
                position_size=position_size,
                event_id=event.event_id,
                timestamp=reasoning_chain.timestamp,
                message="Decision ready event published - will trigger signal_update broadcast to frontend"
            )
            
        except Exception as e:
            logger.error(
                "decision_ready_event_emit_failed",
                error=str(e),
                exc_info=True
            )
    
    async def generate_reasoning(self, request: MCPReasoningRequest) -> MCPReasoningChain:
        """Generate 7-step reasoning chain (including trade adjudication)."""
        normalized_context = self._normalize_market_context_predictions(
            request.market_context
        )
        request = request.model_copy(update={"market_context": normalized_context})
        model_predictions = self._get_model_predictions(normalized_context)

        # Enforce that reasoning is only generated when real model predictions
        # are present. This prevents pseudo-decisions based solely on features
        # or other fallbacks.
        if not model_predictions:
            logger.error(
                "reasoning_generate_no_model_predictions",
                message="generate_reasoning called without model_predictions in market_context.",
            )
            raise NoHealthyModelPredictionsError(
                "Cannot generate reasoning without model_predictions in market_context."
            )

        chain_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        steps: List[ReasoningStep] = []
        step_timings_ms: Dict[str, float] = {}

        async def _run_step(step_name: str, coro):
            t0 = time.perf_counter()
            result = await coro
            step_timings_ms[step_name] = round((time.perf_counter() - t0) * 1000.0, 2)
            if step_timings_ms[step_name] > 100.0:
                logger.warning(
                    "reasoning_step_slow",
                    step=step_name,
                    duration_ms=step_timings_ms[step_name],
                )
            return result
        
        # Steps 1–4 are independent; run concurrently for lower latency.
        step1, step2, step3, step4 = await asyncio.gather(
            _run_step("situational_assessment", self._step1_situational_assessment(request)),
            _run_step("historical_context", self._step2_historical_context(request, chain_id)),
            _run_step("model_consensus", self._step3_model_consensus(request)),
            _run_step("risk_assessment", self._step4_risk_assessment(request, [])),
        )
        steps.extend([step1, step2, step3, step4])
        
        # Step 5: Decision Synthesis
        step5 = await _run_step(
            "decision_synthesis",
            self._step5_decision_synthesis(request, steps),
        )
        steps.append(step5)

        # Step 6: Trade adjudication (strategy vs ML validation)
        step5b = await _run_step(
            "trade_adjudication",
            asyncio.to_thread(self._step_trade_adjudication, request),
        )
        steps.append(step5b)
        
        # Extract model predictions and features
        feature_context = request.market_context.get("features", {})

        # Step 7: Confidence Calibration
        step7 = await _run_step(
            "confidence_calibration",
            self._step7_confidence_calibration(request, steps, model_predictions),
        )
        steps.append(step7)
        
        if isinstance(request.market_context.get("strategy_candidate"), dict):
            final_conclusion = step5b.description
        else:
            final_conclusion = step5.description

        logger.info(
            "reasoning_chain_generated",
            chain_id=chain_id,
            step_count=len(steps),
            step_timings_ms=step_timings_ms,
        )

        return MCPReasoningChain(
            chain_id=chain_id,
            timestamp=timestamp,
            market_context=request.market_context,
            steps=steps,
            conclusion=final_conclusion,
            final_confidence=step7.confidence,
            model_predictions=model_predictions,
            feature_context=[{"name": k, "value": v} for k, v in feature_context.items()]
        )
    
    def _step_trade_adjudication(self, request: MCPReasoningRequest) -> ReasoningStep:
        """Adjudicate deterministic thesis vs ML validation (strategy-first pipeline)."""
        mc = request.market_context
        strat = mc.get("strategy_candidate") if isinstance(mc.get("strategy_candidate"), dict) else {}
        ml_val = mc.get("ml_validation") if isinstance(mc.get("ml_validation"), dict) else {}
        ts = mc.get("trade_score") if isinstance(mc.get("trade_score"), dict) else {}

        thesis_sig = str(strat.get("signal") or "HOLD").upper()
        ml_sig = str(
            (mc.get("v43_dedicated_decision") or {}).get("ml_candidate_signal") or "HOLD"
        ).upper()
        score = float(ts.get("score") or 0.0)
        passed = bool(ts.get("passed", False))
        ml_confirms = bool(
            ml_val.get("final_long")
            or ml_val.get("final_short")
            or ml_val.get("confirms_long")
            or ml_val.get("confirms_short")
        )

        evidence = [
            f"thesis_signal={thesis_sig}",
            f"ml_candidate={ml_sig}",
            f"ml_confirms={ml_confirms}",
            f"trade_score={score:.1f} passed={passed}",
        ]

        entry = thesis_sig in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL")
        same_dir = (
            (thesis_sig in ("BUY", "STRONG_BUY") and ml_sig in ("BUY", "STRONG_BUY"))
            or (thesis_sig in ("SELL", "STRONG_SELL") and ml_sig in ("SELL", "STRONG_SELL"))
        )

        if entry and same_dir and ml_confirms and passed:
            desc = f"{thesis_sig} - trade adjudication: thesis and ML agree (score={score:.0f})"
            conf = 0.75
            evidence.append("adjudication_verdict=agree")
        elif entry and not ml_confirms:
            desc = f"HOLD - trade adjudication: thesis {thesis_sig} lacks ML confirmation"
            conf = 0.4
            evidence.append("adjudication_verdict=ml_reject")
        elif entry and not same_dir:
            desc = f"HOLD - trade adjudication: thesis {thesis_sig} vs ML {ml_sig} conflict"
            conf = 0.35
            evidence.append("adjudication_verdict=conflict")
        elif entry and not passed:
            desc = f"HOLD - trade adjudication: score {score:.0f} below minimum"
            conf = 0.3
            evidence.append("adjudication_verdict=score_reject")
        else:
            desc = "HOLD - trade adjudication: no aligned strategy+ML setup"
            conf = 0.25
            evidence.append("adjudication_verdict=flat")

        return ReasoningStep(
            step_number=6,
            step_name="Trade Adjudication",
            description=desc,
            evidence=evidence,
            confidence=conf,
            timestamp=datetime.utcnow(),
        )
    
    async def _step1_situational_assessment(self, request: MCPReasoningRequest) -> ReasoningStep:
        """Step 1: Assess current market situation."""

        context = request.market_context
        features = context.get("features", {})

        # Assess market conditions
        evidence = []
        if features.get("rsi_14", 50) > 70:
            evidence.append("RSI indicates overbought conditions")
        elif features.get("rsi_14", 50) < 30:
            evidence.append("RSI indicates oversold conditions")

        if features.get("volatility", 0) > 5:
            evidence.append("High volatility detected")

        # Perpetual futures regime assessment
        funding_rate = float(features.get("funding_rate", 0.0) or 0.0)
        funding_spike = float(features.get("funding_spike", 0.0) or 0.0)
        oi_confirm = float(features.get("oi_price_confirm", 0.0) or 0.0)
        basis_pct = float(features.get("basis_pct", 0.0) or 0.0)
        long_squeeze = float(features.get("long_squeeze_risk", 0.0) or 0.0)
        short_squeeze = float(features.get("short_squeeze_risk", 0.0) or 0.0)
        ob_imbalance = float(features.get("ob_imbalance", 0.0) or 0.0)

        perp_regime = "neutral"
        if funding_rate > 0.0003 and funding_spike > 0.0:
            perp_regime = "overheated_long"
            evidence.append("Funds heavy long bias — elevated crowding risk")
        elif funding_rate < -0.0002 and funding_spike > 0.0:
            perp_regime = "overheated_short"
            evidence.append("Funds heavy short bias — elevated crowding risk")
        elif basis_pct > 0.002:
            perp_regime = "contango_heavy"
            evidence.append("Contango structure" )
        elif basis_pct < -0.002:
            perp_regime = "backwardation"
            evidence.append("Backwardation structure")

        if max(long_squeeze, short_squeeze) > 0:
            squeeze_type = "long" if long_squeeze > short_squeeze else "short"
            evidence.append(f"{squeeze_type.capitalize()} squeeze risk detected")

        if abs(ob_imbalance) > 0.2:
            evidence.append("Orderbook imbalance indicates directional pressure")

        # Store perp info in context for downstream usage
        context["perp_regime"] = perp_regime
        context["squeeze_risk"] = max(long_squeeze, short_squeeze)
        context["squeeze_type"] = "long" if long_squeeze > short_squeeze else "short"
        context["ob_imbalance"] = ob_imbalance
        context["funding_rate"] = funding_rate

        # Funding warning if expensive carry runaway
        if abs(funding_rate) > 0.0005:
            evidence.append("Funding cost elevated — consider position reduction")

        # Use feature quality score as confidence when available; otherwise fall
        # back to the qualitative feature_quality label, and finally to 0.0.
        raw_quality = context.get("quality_score")
        if isinstance(raw_quality, (int, float)):
            quality_score = max(0.0, min(1.0, float(raw_quality)))
        else:
            # Older callers may only provide a qualitative feature_quality
            # string such as "high", "medium", "low", or "degraded".
            feature_quality = context.get("feature_quality")
            if isinstance(feature_quality, str):
                quality_mapping = {
                    "high": 1.0,
                    "medium": 0.7,
                    "low": 0.4,
                    "degraded": 0.1,
                }
                quality_score = quality_mapping.get(feature_quality.lower(), 0.0)
            else:
                quality_score = 0.0

        confidence = quality_score

        # Include quality score in evidence if available
        if quality_score > 0:
            evidence.append(f"Data quality: {quality_score:.2f}")
        else:
            evidence.append("Data quality score unavailable")

        data_freshness_seconds = self._compute_data_freshness_seconds(
            request.market_context.get("timestamp")
        )

        return ReasoningStep(
            step_number=1,
            step_name="Situational Assessment",
            description="Current market conditions analyzed",
            evidence=evidence or ["Market conditions stable"],
            confidence=confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds,
            feature_quality_score=quality_score if quality_score > 0 else None
        )
    
    async def _step2_historical_context(self, request: MCPReasoningRequest, chain_id: str) -> ReasoningStep:
        """Step 2: Retrieve similar historical contexts."""

        from agent.memory.vector_store import DecisionContext

        evidence = []
        confidence = 0.0
        similar_contexts = None  # Initialize to avoid UnboundLocalError
        avg_similarity = 0.0
        historical_win_rate: Optional[float] = None

        if request.use_memory and self.vector_store:
            try:
                # Create DecisionContext from market context for similarity search
                query_context = DecisionContext(
                    context_id=f"query-{chain_id}",
                    symbol=request.symbol,
                    timestamp=datetime.utcnow(),
                    features=request.market_context.get("features", {}),
                    market_context=request.market_context,
                    decision={}  # Empty decision for query context
                )

                similar_contexts = await self.vector_store.get_similar_decisions_with_outcomes(
                    query_context=query_context,
                    limit=3,
                )
                if not similar_contexts:
                    similar_contexts = await self.vector_store.find_similar_contexts(
                        query_context=query_context,
                        limit=3,
                    )

                if similar_contexts:
                    # Extract similarity scores
                    similarity_scores = [score for _, score in similar_contexts]
                    avg_similarity = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0

                    # Use average similarity as confidence, clamped to [0, 1]
                    confidence = max(0.0, min(1.0, avg_similarity))

                    evidence.append(f"Found {len(similar_contexts)} similar historical contexts")
                    evidence.append(f"Average similarity: {avg_similarity:.2f}")
                    with_outcomes = [
                        ctx for ctx, _ in similar_contexts if ctx.outcome is not None
                    ]
                    if with_outcomes:
                        profitable = sum(
                            1
                            for ctx in with_outcomes
                            if float((ctx.outcome or {}).get("pnl", 0) or 0) > 0
                        )
                        historical_win_rate = profitable / len(with_outcomes)
                        evidence.append(
                            f"Similar setups with outcomes: {profitable}/{len(with_outcomes)} profitable"
                        )
                        if getattr(settings, "agent_reflection_policy_feedback_enabled", False):
                            win_factor = max(0.75, min(1.15, 0.85 + 0.30 * historical_win_rate))
                            confidence = max(0.0, min(1.0, confidence * win_factor))
                            evidence.append(
                                f"Historical win-rate adjustment factor: {win_factor:.2f}"
                            )
                else:
                    evidence.append("No similar historical contexts found")
                    avg_similarity = 0.0

            except Exception as e:
                evidence.append(f"Historical context search unavailable: {e}")
        else:
            evidence.append("Vector store not configured")

        step_metadata = (
            {"historical_win_rate": historical_win_rate}
            if historical_win_rate is not None
            else None
        )

        return ReasoningStep(
            step_number=2,
            step_name="Historical Context Retrieval",
            description="Similar historical situations retrieved",
            evidence=evidence,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            similarity_score=avg_similarity if similar_contexts else None,
            step_metadata=step_metadata,
        )
    
    async def _step3_model_consensus(self, request: MCPReasoningRequest) -> ReasoningStep:
        """Step 3: Analyze model consensus."""
        
        model_predictions = self._get_model_predictions(request.market_context)
        
        evidence = []
        if model_predictions:
            # Calculate weighted average by confidence
            total_weight = 0.0
            weighted_sum = 0.0
            
            for p in model_predictions:
                prediction = p.get("prediction", 0.0)
                confidence = p.get("confidence", 0.0)  # Treat missing confidence as 0.0
                # Ensure confidence is in valid range [0, 1]
                confidence = max(0.0, min(1.0, confidence))
                
                weighted_sum += prediction * confidence
                total_weight += confidence
            
            if total_weight > 0:
                consensus = weighted_sum / total_weight
                avg_confidence = total_weight / len(model_predictions)
            else:
                # All confidences are zero – use simple average and reflect uncertainty in avg_confidence
                consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                avg_confidence = 0.0
            
            # Model disagreement filter: dampen consensus when predictions disagree strongly
            predictions_vals = [p.get("prediction", 0) for p in model_predictions]
            thresh = getattr(settings, "model_disagreement_threshold", 0.6)
            if len(predictions_vals) > 1:
                pred_stdev = statistics.stdev(predictions_vals)
                if pred_stdev > thresh:
                    # Scalping: reduce excessive consensus suppression when models disagree.
                    # Keep at least 50% of the consensus rather than allowing near-zero collapse.
                    damping_factor = max(0.5, 1.0 - 0.5 * (pred_stdev - thresh))
                    consensus_before = consensus
                    evidence.append(
                        f"High model disagreement (stdev={pred_stdev:.2f}) — signal suppressed"
                    )
                    consensus *= damping_factor
                    if getattr(settings, "diagnostics_enabled", True):
                        logger.info(
                            "model_consensus_dampened",
                            symbol=request.symbol,
                            pred_stdev=float(pred_stdev),
                            threshold=float(thresh),
                            damping_factor=float(damping_factor),
                            consensus_before=float(consensus_before),
                            consensus_after=float(consensus),
                            models=len(predictions_vals),
                        )

            evidence.append(f"Model consensus: {consensus:.2f} ({len(model_predictions)} models, avg confidence: {avg_confidence:.2f})")
            
            consensus_label_thr = abs(
                float(getattr(settings, "reasoning_consensus_label_threshold", 0.5))
            )
            if consensus > consensus_label_thr:
                evidence.append("Strong bullish consensus")
            elif consensus < -consensus_label_thr:
                evidence.append("Strong bearish consensus")
            else:
                evidence.append("Mixed signals from models")
        else:
            evidence.append("No model predictions available")
            consensus = 0.0
            avg_confidence = 0.0

        data_freshness_seconds = self._compute_data_freshness_seconds(
            request.market_context.get("timestamp")
        )

        return ReasoningStep(
            step_number=3,
            step_name="Model Consensus Analysis",
            description="Multi-model predictions aggregated",
            evidence=evidence,
            confidence=avg_confidence if model_predictions else 0.0,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds
        )
    
    async def _step4_risk_assessment(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 4: Assess trading risks using live portfolio and drawdown metrics."""

        evidence: List[str] = []
        risk_level = "medium"
        confidence = 0.35
        mc = request.market_context or {}

        features = mc.get("features", {}) if isinstance(mc.get("features"), dict) else {}
        volatility = features.get("volatility")
        if volatility is not None:
            try:
                vol_f = float(volatility)
                if vol_f > 5:
                    risk_level = "high"
                    confidence += 0.15
                    evidence.append(f"High volatility ({vol_f:.2f})")
                elif vol_f < 2:
                    risk_level = "low"
                    confidence += 0.2
                    evidence.append(f"Low volatility ({vol_f:.2f})")
                else:
                    confidence += 0.1
                    evidence.append(f"Moderate volatility ({vol_f:.2f})")
            except (TypeError, ValueError):
                evidence.append("Volatility parse error")
        else:
            evidence.append("Volatility data unavailable")

        portfolio_heat = mc.get("portfolio_heat")
        if portfolio_heat is not None:
            try:
                heat = float(portfolio_heat)
                max_heat = float(getattr(settings, "portfolio_max_heat_ratio", 0.85) or 0.85)
                if heat > max_heat:
                    risk_level = "high"
                    confidence = max(0.0, confidence - 0.2)
                    evidence.append(f"Portfolio heat above cap ({heat:.3f}>{max_heat:.3f})")
                elif heat > (max_heat - 0.1):
                    confidence = max(0.0, confidence - 0.08)
                    evidence.append(f"Portfolio heat elevated ({heat:.3f})")
                else:
                    confidence += 0.12
                    evidence.append(f"Portfolio heat acceptable ({heat:.3f})")
            except (TypeError, ValueError):
                evidence.append("Portfolio heat parse error")

        drawdown = mc.get("current_drawdown_pct") or mc.get("max_drawdown_current")
        if drawdown is not None:
            try:
                dd = float(drawdown)
                if dd > 0.15:
                    risk_level = "high"
                    confidence = max(0.0, confidence - 0.15)
                    evidence.append(f"Drawdown elevated ({dd:.1%})")
                elif dd > 0.08:
                    confidence = max(0.0, confidence - 0.05)
                    evidence.append(f"Drawdown moderate ({dd:.1%})")
                else:
                    confidence += 0.1
                    evidence.append(f"Drawdown contained ({dd:.1%})")
            except (TypeError, ValueError):
                evidence.append("Drawdown parse error")

        corr = mc.get("position_correlation")
        if corr is not None:
            try:
                conc = float(corr)
                if conc > 0.85:
                    confidence = max(0.0, confidence - 0.1)
                    evidence.append(f"High side concentration ({conc:.2f})")
                else:
                    confidence += 0.05
                    evidence.append(f"Side concentration ({conc:.2f})")
            except (TypeError, ValueError):
                pass

        confidence = max(0.0, min(1.0, confidence))
        data_freshness_seconds = self._compute_data_freshness_seconds(mc.get("timestamp"))

        return ReasoningStep(
            step_number=4,
            step_name="Risk Assessment",
            description=f"Risk level: {risk_level}",
            evidence=evidence,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds,
        )
    
    async def _step5_decision_synthesis(self, request: MCPReasoningRequest, previous_steps: List[ReasoningStep]) -> ReasoningStep:
        """Step 5: Synthesize final decision."""
        
        model_predictions = self._get_model_predictions(request.market_context)

        strat = request.market_context.get("strategy_candidate")
        if isinstance(strat, dict) and strat.get("signal"):
            thesis_sig = str(strat.get("signal") or "HOLD")
            ts = request.market_context.get("trade_score") or {}
            score = float(ts.get("score") or 0.0) if isinstance(ts, dict) else 0.0
            v43_dec = request.market_context.get("v43_dedicated_decision") or {}
            evidence = list(v43_dec.get("evidence") or []) if isinstance(v43_dec, dict) else []
            evidence.append(f"strategy-first synthesis thesis={thesis_sig} score={score:.0f}")
            conclusion = f"HOLD - awaiting policy ({thesis_sig} thesis, score={score:.0f})"
            data_freshness_seconds = self._compute_data_freshness_seconds(
                request.market_context.get("timestamp")
            )
            return ReasoningStep(
                step_number=5,
                step_name="Decision Synthesis",
                description=conclusion,
                evidence=evidence,
                confidence=float(strat.get("confidence") or 0.5),
                timestamp=datetime.utcnow(),
                data_freshness_seconds=data_freshness_seconds,
            )

        v43_dec = request.market_context.get("v43_dedicated_decision")
        if isinstance(v43_dec, dict) and v43_dec.get("enabled"):
            conclusion = str(v43_dec.get("conclusion", "HOLD - v43"))
            avg_confidence = float(v43_dec.get("confidence", 0.5))
            evidence = list(v43_dec.get("evidence") or [])
            evidence.append("v43 diagnostic path — MTF synthesis skipped")
            data_freshness_seconds = self._compute_data_freshness_seconds(
                request.market_context.get("timestamp")
            )
            return ReasoningStep(
                step_number=5,
                step_name="Decision Synthesis",
                description=conclusion,
                evidence=evidence,
                confidence=max(0.0, min(1.0, avg_confidence)),
                timestamp=datetime.utcnow(),
                data_freshness_seconds=data_freshness_seconds,
            )

        if not model_predictions:
            conclusion = "HOLD - Insufficient signal strength"
            evidence = ["No model predictions available"]
            consensus = 0.0
            avg_confidence = 0.0
            if getattr(settings, "diagnostics_enabled", True):
                logger.info(
                    "reasoning_hold_exit",
                    symbol=request.symbol,
                    reason="no_model_predictions",
                    consensus=float(consensus),
                    strong_thresh=None,
                    mild_thresh=None,
                    vol=None,
                    avg_confidence=float(avg_confidence),
                    total_models=0,
                    message="Step 5 produced HOLD due to missing model predictions.",
                )
        else:
            # Skip MTF synthesis when predictions already encode regime/context (JackSparrow v43).
            mtf_out = None
            all_jacksparrow_v43 = model_predictions and all(
                isinstance(p, dict)
                and (p.get("context") or {}).get("format") == "jacksparrow_v43"
                for p in model_predictions
            )
            if all_jacksparrow_v43:
                mtf_out = None
            elif not bool(getattr(settings, "single_model_mode_enabled", False)):
                mtf_out = synthesize_mtf_trading_decision(
                    model_predictions, settings, symbol=request.symbol
                )
            if mtf_out is not None:
                decision_code, conclusion, avg_confidence, mtf_evidence = mtf_out
                hold_bucket = None
                if decision_code == "HOLD":
                    hold_bucket = self._extract_hold_bucket(conclusion, mtf_evidence)
                if getattr(settings, "diagnostics_enabled", True):
                    logger.info(
                        "reasoning_stage5_mtf_decision",
                        symbol=request.symbol,
                        decision=decision_code,
                        avg_confidence=float(avg_confidence),
                        hold_bucket=hold_bucket,
                    )
                evidence = list(mtf_evidence) + [
                    f"Decision code: {decision_code}",
                    f"Based on {len(previous_steps)} analysis steps",
                ]
                if hold_bucket:
                    evidence.append(f"HOLD bucket: {hold_bucket}")
                data_freshness_seconds = self._compute_data_freshness_seconds(
                    request.market_context.get("timestamp")
                )
                return ReasoningStep(
                    step_number=5,
                    step_name="Decision Synthesis",
                    description=conclusion,
                    evidence=evidence,
                    confidence=max(0.0, min(1.0, float(avg_confidence))),
                    timestamp=datetime.utcnow(),
                    data_freshness_seconds=data_freshness_seconds,
                )

            # Separate classifier and regressor predictions
            # Regressors predict prices directly and are generally more reliable for price direction
            classifier_predictions = [
                p for p in model_predictions 
                if p.get("model_type", "").lower() == "classifier"
            ]
            regressor_predictions = [
                p for p in model_predictions 
                if p.get("model_type", "").lower() == "regressor"
            ]
            
            # Calculate consensus for each type
            classifier_consensus = 0.0
            regressor_consensus = 0.0
            classifier_confidence = 0.0
            regressor_confidence = 0.0
            
            if classifier_predictions:
                classifier_weight = 0.0
                classifier_sum = 0.0
                for p in classifier_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    classifier_sum += prediction * confidence
                    classifier_weight += confidence
                if classifier_weight > 0:
                    classifier_consensus = classifier_sum / classifier_weight
                    classifier_confidence = classifier_weight / len(classifier_predictions)
            
            if regressor_predictions:
                regressor_weight = 0.0
                regressor_sum = 0.0
                for p in regressor_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    regressor_sum += prediction * confidence
                    regressor_weight += confidence
                if regressor_weight > 0:
                    regressor_consensus = regressor_sum / regressor_weight
                    regressor_confidence = regressor_weight / len(regressor_predictions)
            
            # Combine consensus: prefer regressors if available (they predict prices directly)
            # If both exist, use weighted average with higher weight for regressors (2:1 ratio)
            if regressor_predictions and classifier_predictions:
                # Both types present: weighted average favoring regressors
                regressor_weight_ratio = 2.0  # Regressors get 2x weight
                total_combined_weight = regressor_confidence * regressor_weight_ratio + classifier_confidence
                if total_combined_weight > 0:
                    consensus = (
                        regressor_consensus * regressor_confidence * regressor_weight_ratio +
                        classifier_consensus * classifier_confidence
                    ) / total_combined_weight
                    avg_confidence = total_combined_weight / (regressor_weight_ratio + 1.0)
                else:
                    consensus = (regressor_consensus + classifier_consensus) / 2.0
                    avg_confidence = (regressor_confidence + classifier_confidence) / 2.0
                evidence_detail = f"Regressor consensus: {regressor_consensus:.2f} (weight: {regressor_weight_ratio}x), Classifier consensus: {classifier_consensus:.2f}"
            elif regressor_predictions:
                # Only regressors available
                consensus = regressor_consensus
                avg_confidence = regressor_confidence
                evidence_detail = f"Regressor consensus: {consensus:.2f} ({len(regressor_predictions)} models)"
            elif classifier_predictions:
                # Only classifiers available
                consensus = classifier_consensus
                avg_confidence = classifier_confidence
                evidence_detail = f"Classifier consensus: {consensus:.2f} ({len(classifier_predictions)} models)"
            else:
                # Fallback: model_type missing or not classifier/regressor – treat all as one group
                total_weight = 0.0
                weighted_sum = 0.0
                for p in model_predictions:
                    prediction = p.get("prediction", 0.0)
                    confidence = max(0.0, min(1.0, p.get("confidence", 0.5)))
                    weighted_sum += prediction * confidence
                    total_weight += confidence
                if total_weight > 0:
                    consensus = weighted_sum / total_weight
                    avg_confidence = total_weight / len(model_predictions)
                else:
                    consensus = sum(p.get("prediction", 0) for p in model_predictions) / len(model_predictions)
                    # Use mean of confidences (default 0.5 when missing) so step 5 never forces 0
                    avg_confidence = sum(
                        max(0.0, min(1.0, p.get("confidence", 0.5)))
                        for p in model_predictions
                    ) / len(model_predictions) if model_predictions else 0.0
                evidence_detail = f"Combined consensus: {consensus:.2f} (fallback calculation)"
            
            # Adaptive consensus thresholds by volatility (when vol available); else fixed
            features = request.market_context.get("features", {})
            vol = features.get("volatility")
            if vol is not None:
                if vol > 5:
                    strong_thresh, mild_thresh = 0.45, 0.20
                elif vol < 1.5:
                    strong_thresh, mild_thresh = 0.35, 0.15
                else:
                    strong_thresh, mild_thresh = 0.40, 0.18
            else:
                strong_thresh, mild_thresh = 0.40, 0.18

            strong_thresh, mild_thresh = await apply_redis_hold_band_overrides(
                strong_thresh, mild_thresh
            )

            # Preserve high-separation class probabilities: when buy/sell margins are
            # consistently strong, slightly narrow hold bands to avoid over-HOLD bias.
            prob_margins: List[float] = []
            for p in model_predictions:
                ctx = p.get("context") if isinstance(p, dict) else None
                entry_proba = (
                    ctx.get("entry_proba")
                    if isinstance(ctx, dict) and isinstance(ctx.get("entry_proba"), dict)
                    else None
                )
                if not entry_proba:
                    continue
                try:
                    buy_p = float(entry_proba.get("buy", 0.0))
                    sell_p = float(entry_proba.get("sell", 0.0))
                except (TypeError, ValueError):
                    continue
                prob_margins.append(abs(buy_p - sell_p))

            margin_mean = (
                sum(prob_margins) / len(prob_margins) if prob_margins else 0.0
            )
            if margin_mean >= 0.18:
                strong_thresh = max(0.30, strong_thresh - 0.03)
                mild_thresh = max(0.10, mild_thresh - 0.02)
            elif margin_mean >= 0.12:
                strong_thresh = max(0.32, strong_thresh - 0.02)
                mild_thresh = max(0.11, mild_thresh - 0.01)

            decision_code = "HOLD"
            if consensus > strong_thresh:
                decision_code = "STRONG_BUY"
                conclusion = "STRONG_BUY - High confidence bullish signal"
            elif consensus > mild_thresh:
                decision_code = "BUY"
                conclusion = "BUY - Moderate bullish signal"
            elif consensus < -strong_thresh:
                decision_code = "STRONG_SELL"
                conclusion = "STRONG_SELL - High confidence bearish signal"
            elif consensus < -mild_thresh:
                decision_code = "SELL"
                conclusion = "SELL - Moderate bearish signal"
            else:
                conclusion = "HOLD - Mixed signals, waiting for clearer direction"

            if getattr(settings, "diagnostics_enabled", True):
                hold_bucket = "consensus_in_hold_band" if decision_code == "HOLD" else None
                logger.info(
                    "reasoning_stage5_decision",
                    symbol=request.symbol,
                    decision=decision_code,
                    consensus=float(consensus),
                    strong_thresh=float(strong_thresh),
                    mild_thresh=float(mild_thresh),
                    vol=float(vol) if vol is not None else None,
                    avg_confidence=float(avg_confidence),
                    total_models=len(model_predictions),
                    classifiers=len(classifier_predictions),
                    regressors=len(regressor_predictions),
                    probability_margin_mean=float(margin_mean),
                    hold_bucket=hold_bucket,
                )
                if decision_code == "HOLD":
                    logger.info(
                        "reasoning_hold_exit",
                        symbol=request.symbol,
                        reason="consensus_in_hold_band",
                        hold_bucket="consensus_in_hold_band",
                        consensus=float(consensus),
                        strong_thresh=float(strong_thresh),
                        mild_thresh=float(mild_thresh),
                        vol=float(vol) if vol is not None else None,
                        avg_confidence=float(avg_confidence),
                        total_models=len(model_predictions),
                        probability_margin_mean=float(margin_mean),
                    )
            
            evidence = [
                f"Final consensus: {consensus:.2f} (weighted avg confidence: {avg_confidence:.2f})",
                evidence_detail,
                f"Based on {len(previous_steps)} analysis steps",
                f"Total models: {len(model_predictions)} ({len(classifier_predictions)} classifiers, {len(regressor_predictions)} regressors)"
            ]

        data_freshness_seconds = self._compute_data_freshness_seconds(
            request.market_context.get("timestamp")
        )

        return ReasoningStep(
            step_number=5,
            step_name="Decision Synthesis",
            description=conclusion,
            evidence=evidence,
            confidence=avg_confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=data_freshness_seconds
        )
    
    async def _step7_confidence_calibration(
        self,
        request: MCPReasoningRequest,
        steps: List[ReasoningStep],
        model_predictions: List[Dict[str, Any]],
    ) -> ReasoningStep:
        """Step 7: Calibrate final confidence using weighted average and consistency adjustment.

        When learning is disabled, calibration uses only step confidences and a consistency
        adjustment (no historical accuracy). If learning is enabled, historical calibration
        could be integrated here (e.g. w * historical_accuracy + (1-w) * raw_confidence).
        """

        # Weighted average with step importance weights.
        # Step 6 (trade adjudication) is the decisive gate on the v43 path.
        decision_step = self._resolve_decision_step_for_hold(request, steps)
        decision_desc = (decision_step.description if decision_step else "").upper()
        is_hold = "HOLD" in decision_desc

        step_weights = {
            1: 0.01,  # Situational assessment
            2: 0.12,  # Historical context
            3: 0.30,  # Model consensus
            4: 0.04,  # Risk assessment
            5: 0.25,  # Decision synthesis
            6: 0.28,  # Trade adjudication (final BUY/SELL/HOLD gate)
        }

        calibration_steps = [s for s in steps if s.step_number <= 6]
        weighted_sum = sum(
            step.confidence * step_weights.get(step.step_number, 0.1)
            for step in calibration_steps
        )
        total_weight = sum(
            step_weights.get(step.step_number, 0.1) for step in calibration_steps
        )
        base_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Consistency adjustment (less aggressive)
        if calibration_steps:
            confidence_range = max(step.confidence for step in calibration_steps) - min(
                step.confidence for step in calibration_steps
            )
            # Use consistency as a small adjustment factor, not a multiplier
            consistency_adjustment = max(0.95, 1.0 - (confidence_range * 0.12))
            # For actionable non-HOLD outputs, avoid strong confidence collapse.
            if not is_hold:
                consistency_adjustment = max(0.98, consistency_adjustment)
        else:
            consistency_adjustment = 1.0

        final_confidence = base_confidence * consistency_adjustment
        reasoning_only_confidence = final_confidence

        # Apply model_avg floor only when reasoning confidence is meaningfully positive
        if model_predictions:
            model_confidences = [max(0.0, min(1.0, float(p.get("confidence", 0)))) for p in model_predictions]
            model_avg = sum(model_confidences) / len(model_confidences) if model_confidences else 0.0
            if reasoning_only_confidence > 0.1 and model_avg > 0:
                final_confidence = max(final_confidence, model_avg * 0.8)
            # Unanimous HOLD: all models agree on neutral (confidence 0). Avoid showing 0% in UI.
            if model_avg == 0 and model_confidences:
                final_confidence = max(final_confidence, 0.5)

            # Probability separation boost: if entry buy/sell margins are strong
            # across models, confidence should reflect that separation.
            prob_margins: List[float] = []
            for p in model_predictions:
                ctx = p.get("context") if isinstance(p, dict) else None
                entry_proba = (
                    ctx.get("entry_proba")
                    if isinstance(ctx, dict) and isinstance(ctx.get("entry_proba"), dict)
                    else None
                )
                if not entry_proba:
                    continue
                try:
                    buy_p = float(entry_proba.get("buy", 0.0))
                    sell_p = float(entry_proba.get("sell", 0.0))
                except (TypeError, ValueError):
                    continue
                prob_margins.append(abs(buy_p - sell_p))

            margin_mean = sum(prob_margins) / len(prob_margins) if prob_margins else 0.0
            if margin_mean > 0.10 and not is_hold:
                # Cap boost so confidence remains conservative.
                final_confidence += min(0.08, (margin_mean - 0.10) * 0.4)

        # v43 dedicated path: actionable BUY/SELL must clear AI minimal entry confidence
        # after weighted calibration (single-model + step weights cap below 0.7 otherwise).
        mc = request.market_context or {}
        v43_dec = mc.get("v43_dedicated_decision")
        if (
            isinstance(v43_dec, dict)
            and v43_dec.get("enabled")
            and (v43_dec.get("final_long") or v43_dec.get("final_short"))
        ):
            ai_floor = float(getattr(settings, "ai_signal_min_entry_confidence", 0.7) or 0.7)
            floor_threshold = ai_floor * 0.85
            if base_confidence >= floor_threshold:
                final_confidence = max(final_confidence, min(1.0, ai_floor * 0.985))

        # Detect fallback scenario for logging/diagnostics
        is_fallback_scenario = not model_predictions or all(
            p.get("confidence", 0) == 0 for p in model_predictions
        )

        # Ensure final confidence is in valid range
        final_confidence = max(0.0, min(1.0, final_confidence))

        historical_win_rate: Optional[float] = None
        step2 = next((s for s in steps if s.step_number == 2), None)
        if step2 and isinstance(step2.step_metadata, dict):
            hr = step2.step_metadata.get("historical_win_rate")
            if hr is not None:
                try:
                    historical_win_rate = float(hr)
                except (TypeError, ValueError):
                    historical_win_rate = None

        learning_diagnostics: Dict[str, Any] = {}
        if self.learning_system:
            try:
                final_confidence, learning_diagnostics = (
                    await self.learning_system.calibrate_reasoning_confidence(
                        final_confidence,
                        model_predictions,
                        historical_win_rate=historical_win_rate,
                    )
                )
            except Exception as e:
                logger.warning(
                    "reasoning_learning_calibration_failed",
                    error=str(e),
                    exc_info=True,
                )

        # Log confidence calculation for debugging
        step_confidences = {step.step_number: step.confidence for step in calibration_steps}
        logger.info(
            "confidence_calibration_completed",
            step_confidences=step_confidences,
            base_confidence=base_confidence,
            consistency_adjustment=consistency_adjustment,
            final_confidence=final_confidence,
            is_hold=is_hold,
            decision_step_number=getattr(decision_step, "step_number", None),
            is_fallback_scenario=is_fallback_scenario,
            model_predictions_count=len(model_predictions),
            learning_diagnostics=learning_diagnostics or None,
            message="Confidence calibration step completed"
        )

        evidence_list = [
            f"Weighted base confidence: {base_confidence:.2f}",
            f"Consistency adjustment: {consistency_adjustment:.2f}",
        ]
        if learning_diagnostics:
            evidence_list.append(
                f"Learning calibration: {learning_diagnostics}"
            )

        return ReasoningStep(
            step_number=7,
            step_name="Confidence Calibration",
            description=f"Final confidence: {final_confidence:.2f}",
            evidence=evidence_list
            + [
                f"Final confidence: {final_confidence:.2f}",
                f"Hold decision: {is_hold}",
                f"Fallback scenario: {is_fallback_scenario}",
            ],
            confidence=final_confidence,
            timestamp=datetime.utcnow(),
            data_freshness_seconds=None,
            similarity_score=None,
            feature_quality_score=None,
        )

    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        return {
            "status": "up",
            "vector_store_available": self.vector_store is not None
        }

