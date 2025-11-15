# AI Agent Reasoning & Intelligence Specification

## 🧠 TRUE AI AGENT ARCHITECTURE

### File 2: `02-agent-reasoning-intelligence.md`

## Core Principle: The Agent Must Think, Not Just React

The agent is **NOT** a simple rule-based bot. It must:
1. **Observe** market conditions with context
2. **Reason** about what it observes using structured thinking
3. **Decide** based on multi-factor analysis, not just model outputs
4. **Learn** from outcomes and adapt behavior
5. **Explain** its decisions in human-understandable terms

---

## Agent State Machine (Enhanced)

```python
from enum import Enum
from typing import Optional, Dict, List
from datetime import datetime

class AgentState(Enum):
    INITIALIZING = "initializing"
    OBSERVING = "observing"           # Passively monitoring
    THINKING = "thinking"             # Active analysis in progress
    DELIBERATING = "deliberating"     # Weighing decision options
    EXECUTING = "executing"           # Placing/managing trade
    MONITORING_POSITION = "monitoring_position"  # Active position management
    LEARNING = "learning"             # Post-trade analysis
    DEGRADED = "degraded"             # Partial functionality
    EMERGENCY_STOP = "emergency_stop" # Critical failure

class AgentContext(BaseModel):
    """
    Complete context the agent maintains about its environment
    """
    # Market Context
    current_price: float
    market_regime: str  # "bull_trending", "bear_trending", "ranging", "high_volatility"
    volatility_percentile: float  # 0-100
    volume_profile: str  # "high", "normal", "low"
    time_of_day: str  # "asian", "european", "us", "overnight"
    
    # Portfolio Context
    cash_available: float
    position_size: float
    unrealized_pnl: float
    position_duration_minutes: Optional[int]
    
    # Recent History
    last_10_trades: List[Dict]
    recent_win_rate: float
    consecutive_losses: int
    
    # Agent State
    current_state: AgentState
    last_state_change: datetime
    confidence_level: float  # 0-1, agent's self-assessed confidence
    
    # Risk Metrics
    portfolio_heat: float  # % of capital at risk
    max_drawdown_current: float
    sharpe_ratio_rolling: float

class AgentMemory(BaseModel):
    """
    Long-term memory for the agent
    """
    decision_id: str
    timestamp: datetime
    context: AgentContext
    reasoning_chain: MCPReasoningChain
    decision: MCPDecision
    outcome: Optional[Dict]  # Filled in after trade completes
    embedding: Optional[List[float]]  # Vector embedding for similarity search
```

---

## MCP Reasoning Engine (Core Intelligence)

```python
class MCPReasoningEngine:
    """
    The "brain" of the agent - generates structured reasoning chains
    """
    def __init__(self):
        self.model_registry = MCPModelRegistry()
        self.feature_service = FeatureService()
        self.memory_store = VectorMemoryStore()  # For retrieving similar past situations
        self.context_manager = ContextManager()
        self.confidence_calibrator = ConfidenceCalibrator()
    
    async def generate_reasoning_chain(
        self,
        symbol: str,
        context: AgentContext
    ) -> MCPReasoningChain:
        """
        Generate a complete reasoning chain for current market conditions
        
        This is where the agent "thinks"
        """
        chain_id = str(uuid.uuid4())
        timestamp = datetime.utcnow()
        steps = []
        
        # Step 1: Situational Awareness
        step1 = await self._assess_situation(symbol, context)
        steps.append(step1)
        
        # Step 2: Retrieve Similar Past Situations
        step2 = await self._retrieve_similar_situations(context, step1)
        steps.append(step2)
        
        # Step 3: Model Consensus Analysis
        step3 = await self._analyze_model_predictions(symbol, context)
        steps.append(step3)
        
        # Step 4: Risk Assessment
        step4 = await self._assess_risks(context, step3)
        steps.append(step4)
        
        # Step 5: Decision Synthesis
        step5 = await self._synthesize_decision(steps, context)
        steps.append(step5)
        
        # Step 6: Confidence Calibration
        step6 = await self._calibrate_confidence(steps, context)
        steps.append(step6)
        
        # Generate final conclusion
        conclusion = self._generate_conclusion(steps)
        final_confidence = step6.confidence
        
        return MCPReasoningChain(
            chain_id=chain_id,
            timestamp=timestamp,
            market_context={
                "regime": context.market_regime,
                "volatility": context.volatility_percentile,
                "price": context.current_price
            },
            steps=steps,
            conclusion=conclusion,
            final_confidence=final_confidence
        )
    
    async def _assess_situation(
        self,
        symbol: str,
        context: AgentContext
    ) -> ReasoningStep:
        """
        Step 1: What is happening right now?
        """
        # Get current features
        features = await self.feature_service.get_features(symbol)
        
        # Analyze market regime
        regime_analysis = self._analyze_regime(features, context)
        
        # Check for anomalies
        anomalies = self._detect_anomalies(features)
        
        # Formulate situational assessment
        thought = f"""
        SITUATION ASSESSMENT:
        - Market Regime: {context.market_regime}
        - Volatility: {context.volatility_percentile:.1f}th percentile ({"HIGH" if context.volatility_percentile > 70 else "NORMAL" if context.volatility_percentile > 30 else "LOW"})
        - Volume: {context.volume_profile}
        - Time: {context.time_of_day} session
        
        Current State:
        - Price: ${context.current_price:,.2f}
        - Trend: {regime_analysis['trend']}
        - Momentum: {regime_analysis['momentum']}
        
        Anomalies Detected: {len(anomalies)} 
        {chr(10).join(f"  - {a}" for a in anomalies) if anomalies else "  None"}
        """
        
        evidence = [
            f"feature:{f.name}={f.value:.4f}" for f in features.features[:5]
        ]
        
        confidence = features.quality_score
        
        return ReasoningStep(
            step_number=1,
            thought=thought.strip(),
            evidence=evidence,
            confidence=confidence
        )
    
    async def _retrieve_similar_situations(
        self,
        context: AgentContext,
        situation_step: ReasoningStep
    ) -> ReasoningStep:
        """
        Step 2: What happened in similar situations before?
        """
        # Create embedding of current situation
        situation_embedding = self._embed_situation(context, situation_step)
        
        # Retrieve similar past situations
        similar_memories = await self.memory_store.search_similar(
            embedding=situation_embedding,
            limit=5,
            min_similarity=0.7
        )
        
        if not similar_memories:
            thought = "No sufficiently similar past situations found (novelty detected)"
            confidence = 0.5  # Lower confidence for novel situations
            evidence = []
        else:
            # Analyze outcomes of similar situations
            outcomes = [m.outcome for m in similar_memories if m.outcome]
            
            winning_decisions = sum(
                1 for o in outcomes 
                if o.get('pnl', 0) > 0
            )
            total_decisions = len(outcomes)
            
            avg_pnl = np.mean([o.get('pnl', 0) for o in outcomes])
            
            thought = f"""
            HISTORICAL ANALYSIS:
            Found {len(similar_memories)} similar situations:
            - Win Rate: {winning_decisions}/{total_decisions} ({winning_decisions/total_decisions*100:.1f}%)
            - Average PnL: ${avg_pnl:.2f}
            - Most common decision: {self._get_most_common_decision(similar_memories)}
            
            Key insights from similar situations:
            {self._extract_insights(similar_memories)}
            """
            
            confidence = 0.7 + 0.3 * (winning_decisions / total_decisions if total_decisions > 0 else 0)
            evidence = [f"memory:{m.decision_id}" for m in similar_memories]
        
        return ReasoningStep(
            step_number=2,
            thought=thought.strip(),
            evidence=evidence,
            confidence=confidence
        )
    
    async def _analyze_model_predictions(
        self,
        symbol: str,
        context: AgentContext
    ) -> ReasoningStep:
        """
        Step 3: What do the models predict?
        """
        # Get features
        features = await self.feature_service.get_features(symbol)
        
        # Create MCP request
        request = MCPModelRequest(
            request_id=str(uuid.uuid4()),
            features=features.features,
            context={
                "regime": context.market_regime,
                "portfolio_state": {
                    "position_size": context.position_size,
                    "unrealized_pnl": context.unrealized_pnl
                }
            },
            require_explanation=True
        )
        
        # Get predictions from all models
        predictions = await self.model_registry.get_predictions(request)
        
        # Analyze consensus
        consensus = self._calculate_consensus(predictions)
        
        # Build thought
        model_summaries = []
        for pred in predictions:
            direction = "BULLISH" if pred.prediction.prediction > 0 else "BEARISH"
            strength = abs(pred.prediction.prediction)
            
            model_summaries.append(
                f"  - {pred.prediction.model_name}: {direction} "
                f"(strength: {strength:.2f}, confidence: {pred.prediction.confidence:.2f})\n"
                f"    Reasoning: {pred.prediction.reasoning.split(chr(10))[0]}"
            )
        
        thought = f"""
        MODEL PREDICTIONS:
        Consensus Signal: {consensus['signal']} 
        Consensus Strength: {consensus['strength']:.2f}
        Agreement Level: {consensus['agreement']:.1%}
        
        Individual Models:
        {chr(10).join(model_summaries)}
        
        Consensus Analysis:
        {self._analyze_consensus_quality(predictions, consensus)}
        """
        
        evidence = [f"model:{p.prediction.model_name}" for p in predictions]
        confidence = consensus['confidence']
        
        return ReasoningStep(
            step_number=3,
            thought=thought.strip(),
            evidence=evidence,
            confidence=confidence
        )
    
    def _calculate_consensus(
        self,
        predictions: List[MCPModelResponse]
    ) -> Dict:
        """
        Calculate weighted consensus from model predictions
        """
        if not predictions:
            return {
                "signal": "HOLD",
                "strength": 0.0,
                "confidence": 0.0,
                "agreement": 0.0
            }
        
        # Weight each prediction by model performance and confidence
        weighted_sum = 0.0
        total_weight = 0.0
        
        for pred in predictions:
            # Get model's historical performance
            perf = self.model_registry.performance_tracker.get_performance(
                pred.prediction.model_name
            )
            perf_weight = perf.sharpe_ratio if perf else 1.0
            perf_weight = max(0.1, min(2.0, perf_weight))  # Clamp to [0.1, 2.0]
            
            # Combine performance and confidence
            weight = perf_weight * pred.prediction.confidence
            
            weighted_sum += pred.prediction.prediction * weight
            total_weight += weight
        
        consensus_value = weighted_sum / total_weight if total_weight > 0 else 0.0
        
        # Calculate agreement (variance)
        predictions_array = np.array([
            p.prediction.prediction for p in predictions
        ])
        agreement = 1.0 - np.std(predictions_array)  # Lower variance = higher agreement
        agreement = max(0.0, min(1.0, agreement))
        
        # Determine signal
        if abs(consensus_value) < 0.2:
            signal = "HOLD"
        elif consensus_value > 0.6:
            signal = "STRONG_BUY"
        elif consensus_value > 0.2:
            signal = "BUY"
        elif consensus_value < -0.6:
            signal = "STRONG_SELL"
        else:
            signal = "SELL"
        
        # Confidence in consensus
        confidence = agreement * (abs(consensus_value))
        
        return {
            "signal": signal,
            "strength": abs(consensus_value),
            "confidence": confidence,
            "agreement": agreement,
            "raw_value": consensus_value
        }
    
    async def _assess_risks(
        self,
        context: AgentContext,
        model_step: ReasoningStep
    ) -> ReasoningStep:
        """
        Step 4: What are the risks?
        """
        risks = []
        risk_score = 0.0
        
        # Risk 1: Portfolio Heat
        if context.portfolio_heat > 0.5:
            risks.append(f"⚠️  HIGH portfolio heat: {context.portfolio_heat:.1%} of capital at risk")
            risk_score += 0.3
        
        # Risk 2: Consecutive Losses
        if context.consecutive_losses >= 3:
            risks.append(f"⚠️  {context.consecutive_losses} consecutive losses (potential strategy failure)")
            risk_score += 0.25
        
        # Risk 3: High Volatility
        if context.volatility_percentile > 80:
            risks.append(f"⚠️  Volatility at {context.volatility_percentile:.1f}th percentile (unstable market)")
            risk_score += 0.2
        
        # Risk 4: Low Model Agreement (from previous step)
        model_confidence = model_step.confidence
        if model_confidence < 0.6:
            risks.append(f"⚠️  Low model agreement (confidence: {model_confidence:.2f})")
            risk_score += 0.15
        
        # Risk 5: Drawdown Near Limit
        if context.max_drawdown_current > 0.08:  # 8% drawdown
            risks.append(f"⚠️  Drawdown at {context.max_drawdown_current:.1%} (near limit)")
            risk_score += 0.1
        
        # Calculate recommended position size adjustment
        risk_adjustment = 1.0 - min(1.0, risk_score)
        
        thought = f"""
        RISK ASSESSMENT:
        Overall Risk Level: {risk_score:.2f} ({self._risk_level_text(risk_score)})
        
        Identified Risks:
        {chr(10).join(risks) if risks else "  ✓ No significant risks detected"}
        
        Risk Mitigation:
        - Recommended position size multiplier: {risk_adjustment:.2f}x
        - Stop loss tighter by: {min(20, int(risk_score * 100))}%
        - Maximum holding period: {self._calculate_max_hold_time(risk_score)} minutes
        
        Risk/Reward Assessment:
        {self._assess_risk_reward(context, model_step, risk_score)}
        """
        
        confidence = 1.0 - (risk_score * 0.5)  # High risk = lower confidence
        
        return ReasoningStep(
            step_number=4,
            thought=thought.strip(),
            evidence=[f"risk:{r}" for r in risks],
            confidence=confidence
        )
    
    async def _synthesize_decision(
        self,
        steps: List[ReasoningStep],
        context: AgentContext
    ) -> ReasoningStep:
        """
        Step 5: Synthesize all information into a decision
        """
        # Extract key information from previous steps
        situation = steps[0]
        history = steps[1]
        models = steps[2]
        risks = steps[3]
        
        # Parse model consensus from step 3
        model_signal = self._extract_signal_from_thought(models.thought)
        
        # Combine all factors
        decision_factors = {
            "model_signal": model_signal,
            "model_confidence": models.confidence,
            "historical_success_rate": self._extract_success_rate(history.thought),
            "risk_level": 1.0 - risks.confidence,
            "situation_clarity": situation.confidence
        }
        
        # Decision logic
        if context.position_size != 0:
            # Already in position - should we exit?
            decision = self._decide_position_management(
                context,
                decision_factors
            )
        else:
            # Not in position - should we enter?
            decision = self._decide_entry(
                context,
                decision_factors
            )
        
        thought = f"""
        DECISION SYNTHESIS:
        
        Weighing All Factors:
        • Model Consensus: {model_signal} (confidence: {decision_factors['model_confidence']:.2f})
        • Historical Success: {decision_factors['historical_success_rate']:.1%} in similar situations
        • Risk Level: {decision_factors['risk_level']:.2f}
        • Situation Clarity: {decision_factors['situation_clarity']:.2f}
        
        Decision Matrix:
        {self._generate_decision_matrix(decision_factors)}
        
        RECOMMENDATION: {decision['action']}
        Position Size: {decision['position_size']:.2%} of portfolio
        Rationale: {decision['rationale']}
        """
        
        confidence = self._calculate_final_confidence(decision_factors)
        
        return ReasoningStep(
            step_number=5,
            thought=thought.strip(),
            evidence=[f"factor:{k}={v}" for k, v in decision_factors.items()],
            confidence=confidence
        )
    
    async def _calibrate_confidence(
        self,
        steps: List[ReasoningStep],
        context: AgentContext
    ) -> ReasoningStep:
        """
        Step 6: Calibrate confidence based on agent's historical accuracy
        """
        # Get raw confidence from synthesis
        raw_confidence = steps[-1].confidence
        
        # Get agent's historical calibration data
        calibration = await self.confidence_calibrator.get_calibration(
            confidence_bucket=int(raw_confidence * 10) / 10,
            market_regime=context.market_regime
        )
        
        # Adjust confidence based on historical accuracy
        if calibration:
            actual_success_rate = calibration['success_rate']
            calibrated_confidence = (raw_confidence + actual_success_rate) / 2
            
            adjustment = calibrated_confidence - raw_confidence
            
            thought = f"""
            CONFIDENCE CALIBRATION:
            
            Raw Confidence: {raw_confidence:.2f}
            Historical Accuracy at this confidence level: {actual_success_rate:.2f}
            Calibrated Confidence: {calibrated_confidence:.2f}
            
            Adjustment: {adjustment:+.2f}
            Reason: {self._explain_calibration(raw_confidence, actual_success_rate)}
            
            Final Assessment:
            This decision has a {calibrated_confidence:.1%} probability of success based on:
            - Current analysis
            - Agent's historical performance at this confidence level
            - Market regime ({context.market_regime})
            """
        else:
            # Not enough historical data
            calibrated_confidence = raw_confidence * 0.8  # Conservative adjustment
            
            thought = f"""
            CONFIDENCE CALIBRATION:
            
            Raw Confidence: {raw_confidence:.2f}
            Calibrated Confidence: {calibrated_confidence:.2f}
            
            Note: Applying conservative 20% reduction due to insufficient 
            historical calibration data for this confidence level and market regime.
            """
        
        return ReasoningStep(
            step_number=6,
            thought=thought.strip(),
            evidence=["calibration:applied"],
            confidence=calibrated_confidence
        )
    
    def _generate_conclusion(self, steps: List[ReasoningStep]) -> str:
        """
        Generate final human-readable conclusion
        """
        decision_step = steps[4]  # Synthesis step
        calibration_step = steps[5]  # Calibration step
        
        # Extract decision from synthesis
        decision_match = re.search(r'RECOMMENDATION: (\w+)', decision_step.thought)
        decision = decision_match.group(1) if decision_match else "HOLD"
        
        return f"""
        CONCLUSION:
        After analyzing the current situation, consulting historical data, 
        aggregating model predictions, and assessing risks, the agent recommends: {decision}
        
        Final Confidence: {calibration_step.confidence:.1%}
        
        This decision is based on structured reasoning across {len(steps)} analytical steps,
        calibrated against historical performance.
        """
```

Continue in next part...
