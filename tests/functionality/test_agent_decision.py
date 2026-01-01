"""Test agent decision making functionality (reasoning chain, state machine)."""

from typing import Dict, Any
from datetime import datetime

from tests.functionality.utils import TestSuiteBase, TestResult, TestStatus
from tests.functionality.fixtures import get_shared_agent


class AgentDecisionTestSuite(TestSuiteBase):
    """Test suite for agent decision making."""
    
    def __init__(self, test_name: str = "agent_decision"):
        super().__init__(test_name)
        self.agent = None
    
    async def setup(self):
        """Setup shared resources."""
        try:
            self.agent = await get_shared_agent()
        except Exception as e:
            # Agent initialization failure will be caught in individual tests
            pass
    
    async def run_all_tests(self):
        """Run all decision making tests."""
        await self._test_reasoning_chain_generation()
        await self._test_situational_assessment()
        await self._test_historical_context_retrieval()
        await self._test_model_consensus_analysis()
        await self._test_risk_assessment()
        await self._test_decision_synthesis()
        await self._test_confidence_calibration()
        await self._test_state_machine_transitions()
    
    async def _test_reasoning_chain_generation(self):
        """Test complete 6-step reasoning chain generation."""
        result = TestResult(name="reasoning_chain_generation", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator is None:
                result.status = TestStatus.FAIL
                result.issues.append("MCP orchestrator not available")
                result.solutions.append("Check agent initialization")
            else:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine is None:
                    result.status = TestStatus.FAIL
                    result.issues.append("Reasoning engine not available")
                    result.solutions.append("Check MCP orchestrator initialization")
                else:
                    # Test complete reasoning chain generation
                    symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                    
                    try:
                        from agent.core.reasoning_engine import MCPReasoningRequest
                        
                        request = MCPReasoningRequest(
                            symbol=symbol,
                            market_context={},
                            use_memory=True
                        )
                        
                        reasoning_chain = await reasoning_engine.generate_reasoning(request)
                        
                        if reasoning_chain:
                            result.details["reasoning_chain_generated"] = True
                            
                            # Check for 6 steps
                            steps = getattr(reasoning_chain, "steps", [])
                            result.details["steps_count"] = len(steps)
                            
                            if len(steps) == 6:
                                result.details["complete_reasoning_chain"] = True
                                
                                # Validate step structure
                                step_names = []
                                for step in steps:
                                    step_name = getattr(step, "step_name", None)
                                    if step_name:
                                        step_names.append(step_name)
                                
                                result.details["step_names"] = step_names
                                result.details["all_steps_present"] = len(step_names) == 6
                            else:
                                result.status = TestStatus.WARNING
                                result.issues.append(f"Expected 6 reasoning steps, got {len(steps)}")
                                result.solutions.append("Check reasoning engine step generation logic")
                            
                            # Check final confidence
                            final_confidence = getattr(reasoning_chain, "final_confidence", None)
                            if final_confidence is not None:
                                result.details["has_final_confidence"] = True
                                result.details["final_confidence"] = final_confidence
                            
                            # Check final signal
                            final_signal = getattr(reasoning_chain, "final_signal", None)
                            if final_signal:
                                result.details["has_final_signal"] = True
                                result.details["final_signal"] = final_signal
                        else:
                            result.status = TestStatus.WARNING
                            result.issues.append("Reasoning chain generation returned None")
                            result.solutions.append("Check reasoning engine dependencies and market data")
                    
                    except ImportError:
                        result.status = TestStatus.WARNING
                        result.issues.append("MCPReasoningRequest not available")
                        result.solutions.append("Check reasoning engine imports")
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Reasoning chain generation failed: {e}")
                        result.solutions.append("Check market data availability and reasoning engine configuration")
        
        except Exception as e:
            result.status = TestStatus.FAIL
            result.error = str(e)
            result.issues.append(f"Reasoning chain generation test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_situational_assessment(self):
        """Test Step 1: Situational Assessment."""
        result = TestResult(name="situational_assessment", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    # Test Step 1 directly if method is accessible
                    if hasattr(reasoning_engine, "_step1_situational_assessment"):
                        try:
                            from agent.core.reasoning_engine import MCPReasoningRequest
                            
                            symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                            request = MCPReasoningRequest(
                                symbol=symbol,
                                market_context={},
                                use_memory=True
                            )
                            
                            step1 = await reasoning_engine._step1_situational_assessment(request)
                            
                            if step1:
                                result.details["step1_generated"] = True
                                step_name = getattr(step1, "step_name", None)
                                result.details["step_name"] = step_name
                                
                                if step_name == "situational_assessment" or step_name == "step_1":
                                    result.details["step1_valid"] = True
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
                            result.issues.append(f"Step 1 test failed: {e}")
                    else:
                        # Test indirectly through full reasoning chain
                        try:
                            from agent.core.reasoning_engine import MCPReasoningRequest
                            
                            symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                            request = MCPReasoningRequest(
                                symbol=symbol,
                                market_context={},
                                use_memory=True
                            )
                            
                            reasoning_chain = await reasoning_engine.generate_reasoning(request)
                            
                            if reasoning_chain:
                                steps = getattr(reasoning_chain, "steps", [])
                                if len(steps) > 0:
                                    step1 = steps[0]
                                    step_name = getattr(step1, "step_name", None)
                                    result.details["step1_present"] = True
                                    result.details["step_name"] = step_name
                                    
                                    # Check step content
                                    step_content = getattr(step1, "content", None)
                                    if step_content:
                                        result.details["step1_has_content"] = True
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Situational assessment test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_historical_context_retrieval(self):
        """Test Step 2: Historical Context Retrieval."""
        result = TestResult(name="historical_context_retrieval", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    # Test through full reasoning chain
                    try:
                        from agent.core.reasoning_engine import MCPReasoningRequest
                        
                        symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                        request = MCPReasoningRequest(
                            symbol=symbol,
                            market_context={},
                            use_memory=True  # Enable memory for historical context
                        )
                        
                        reasoning_chain = await reasoning_engine.generate_reasoning(request)
                        
                        if reasoning_chain:
                            steps = getattr(reasoning_chain, "steps", [])
                            if len(steps) >= 2:
                                step2 = steps[1]
                                step_name = getattr(step2, "step_name", None)
                                result.details["step2_present"] = True
                                result.details["step_name"] = step_name
                                
                                # Check if historical context was retrieved
                                step_content = getattr(step2, "content", None)
                                if step_content:
                                    result.details["step2_has_content"] = True
                                    
                                    # Check for memory/historical indicators in content
                                    if isinstance(step_content, dict):
                                        has_memory = "memory" in str(step_content).lower() or "historical" in str(step_content).lower()
                                        result.details["historical_context_retrieved"] = has_memory
                                
                                # Check learning system for memory store
                                learning_system = getattr(self.agent, "learning_system", None)
                                if learning_system:
                                    memory_store = getattr(learning_system, "memory_store", None)
                                    result.details["memory_store_available"] = memory_store is not None
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Historical context test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Historical context retrieval test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_model_consensus_analysis(self):
        """Test Step 3: Model Consensus Analysis."""
        result = TestResult(name="model_consensus_analysis", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    # Test through full reasoning chain
                    try:
                        from agent.core.reasoning_engine import MCPReasoningRequest
                        
                        symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                        request = MCPReasoningRequest(
                            symbol=symbol,
                            market_context={},
                            use_memory=True
                        )
                        
                        reasoning_chain = await reasoning_engine.generate_reasoning(request)
                        
                        if reasoning_chain:
                            steps = getattr(reasoning_chain, "steps", [])
                            if len(steps) >= 3:
                                step3 = steps[2]
                                step_name = getattr(step3, "step_name", None)
                                result.details["step3_present"] = True
                                result.details["step_name"] = step_name
                                
                                # Check for model predictions in context
                                model_registry = getattr(self.agent, "model_registry", None)
                                if model_registry:
                                    models = model_registry.list_models() if hasattr(model_registry, "list_models") else []
                                    result.details["models_available"] = len(models)
                                    
                                    if len(models) > 0:
                                        result.details["can_analyze_consensus"] = True
                                        
                                        # Check if step content includes consensus
                                        step_content = getattr(step3, "content", None)
                                        if step_content:
                                            result.details["step3_has_content"] = True
                                            if isinstance(step_content, dict):
                                                has_consensus = "consensus" in str(step_content).lower() or "prediction" in str(step_content).lower()
                                                result.details["consensus_analyzed"] = has_consensus
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Model consensus test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Model consensus analysis test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_risk_assessment(self):
        """Test Step 4: Risk Assessment."""
        result = TestResult(name="risk_assessment", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    # Check risk manager availability
                    risk_manager = getattr(self.agent, "risk_manager", None)
                    if risk_manager:
                        result.details["risk_manager_available"] = True
                        
                        # Test through full reasoning chain
                        try:
                            from agent.core.reasoning_engine import MCPReasoningRequest
                            
                            symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                            request = MCPReasoningRequest(
                                symbol=symbol,
                                market_context={},
                                use_memory=True
                            )
                            
                            reasoning_chain = await reasoning_engine.generate_reasoning(request)
                            
                            if reasoning_chain:
                                steps = getattr(reasoning_chain, "steps", [])
                                if len(steps) >= 4:
                                    step4 = steps[3]
                                    step_name = getattr(step4, "step_name", None)
                                    result.details["step4_present"] = True
                                    result.details["step_name"] = step_name
                                    
                                    # Check if step content includes risk assessment
                                    step_content = getattr(step4, "content", None)
                                    if step_content:
                                        result.details["step4_has_content"] = True
                                        if isinstance(step_content, dict):
                                            has_risk = "risk" in str(step_content).lower()
                                            result.details["risk_assessed"] = has_risk
                        except Exception as e:
                            result.status = TestStatus.WARNING
                            result.error = str(e)
                    else:
                        result.status = TestStatus.WARNING
                        result.issues.append("Risk manager not available")
                        result.solutions.append("Check risk manager initialization")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Risk assessment test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_decision_synthesis(self):
        """Test Step 5: Decision Synthesis."""
        result = TestResult(name="decision_synthesis", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    try:
                        from agent.core.reasoning_engine import MCPReasoningRequest
                        
                        symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                        request = MCPReasoningRequest(
                            symbol=symbol,
                            market_context={},
                            use_memory=True
                        )
                        
                        reasoning_chain = await reasoning_engine.generate_reasoning(request)
                        
                        if reasoning_chain:
                            steps = getattr(reasoning_chain, "steps", [])
                            if len(steps) >= 5:
                                step5 = steps[4]
                                step_name = getattr(step5, "step_name", None)
                                result.details["step5_present"] = True
                                result.details["step_name"] = step_name
                                
                                # Check for final signal in reasoning chain
                                final_signal = getattr(reasoning_chain, "final_signal", None)
                                if final_signal:
                                    result.details["decision_synthesized"] = True
                                    result.details["final_signal"] = final_signal
                                    
                                    # Validate signal type
                                    valid_signals = ["BUY", "SELL", "STRONG_BUY", "STRONG_SELL", "HOLD"]
                                    if final_signal in valid_signals:
                                        result.details["signal_valid"] = True
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Decision synthesis test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Decision synthesis test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_confidence_calibration(self):
        """Test Step 6: Confidence Calibration."""
        result = TestResult(name="confidence_calibration", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            mcp_orchestrator = getattr(self.agent, "mcp_orchestrator", None)
            if mcp_orchestrator:
                reasoning_engine = getattr(mcp_orchestrator, "reasoning_engine", None)
                if reasoning_engine:
                    try:
                        from agent.core.reasoning_engine import MCPReasoningRequest
                        
                        symbol = getattr(self.agent, "default_symbol", "BTCUSD")
                        request = MCPReasoningRequest(
                            symbol=symbol,
                            market_context={},
                            use_memory=True
                        )
                        
                        reasoning_chain = await reasoning_engine.generate_reasoning(request)
                        
                        if reasoning_chain:
                            steps = getattr(reasoning_chain, "steps", [])
                            if len(steps) >= 6:
                                step6 = steps[5]
                                step_name = getattr(step6, "step_name", None)
                                result.details["step6_present"] = True
                                result.details["step_name"] = step_name
                                
                                # Check final confidence
                                final_confidence = getattr(reasoning_chain, "final_confidence", None)
                                if final_confidence is not None:
                                    result.details["confidence_calibrated"] = True
                                    result.details["final_confidence"] = final_confidence
                                    
                                    # Validate confidence range
                                    if isinstance(final_confidence, (int, float)):
                                        if 0 <= final_confidence <= 100:
                                            result.details["confidence_valid"] = True
                                        else:
                                            result.status = TestStatus.WARNING
                                            result.issues.append(f"Confidence out of range: {final_confidence}")
                                    else:
                                        result.status = TestStatus.WARNING
                                        result.issues.append(f"Confidence not numeric: {type(final_confidence)}")
                                else:
                                    result.status = TestStatus.WARNING
                                    result.issues.append("Final confidence not present")
                    except Exception as e:
                        result.status = TestStatus.WARNING
                        result.error = str(e)
                        result.issues.append(f"Confidence calibration test failed: {e}")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"Confidence calibration test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def _test_state_machine_transitions(self):
        """Test state machine transitions triggered by decisions."""
        result = TestResult(name="state_machine_transitions", status=TestStatus.PASS, duration_ms=0.0)
        start_time = datetime.utcnow()
        
        try:
            if self.agent is None:
                self.agent = await get_shared_agent()
            
            state_machine = getattr(self.agent, "state_machine", None)
            if state_machine is None:
                result.status = TestStatus.FAIL
                result.issues.append("State machine not available")
                result.solutions.append("Check state machine initialization")
            else:
                result.details["state_machine_available"] = True
                
                # Get current state
                current_state = getattr(state_machine, "current_state", None)
                result.details["current_state"] = str(current_state) if current_state else None
                
                # Check state transitions
                transitions = getattr(state_machine, "transitions", None)
                if transitions:
                    result.details["transitions_configured"] = True
                    result.details["transition_count"] = len(transitions) if isinstance(transitions, (list, dict)) else 0
                    
                    # Test decision-triggered transitions
                    # OBSERVING -> THINKING (on significant change)
                    # THINKING -> DELIBERATING (on reasoning complete)
                    # DELIBERATING -> OBSERVING (on HOLD decision)
                    # DELIBERATING -> EXECUTING (on trade decision)
                    
                    result.details["state_transitions_available"] = True
                    
                    # Check context manager for transition triggers
                    context_manager = getattr(state_machine, "context_manager", None)
                    if context_manager:
                        result.details["context_manager_available"] = True
                        
                        # Check if context has decision-related keys
                        get_context = getattr(context_manager, "get_context", None)
                        if get_context:
                            try:
                                context = get_context()
                                if isinstance(context, dict):
                                    decision_keys = [k for k in context.keys() if "decision" in k.lower() or "signal" in k.lower()]
                                    result.details["decision_context_keys"] = decision_keys
                            except Exception:
                                pass
                else:
                    result.status = TestStatus.WARNING
                    result.issues.append("State machine has no transitions configured")
                    result.solutions.append("Check state machine initialization")
        
        except Exception as e:
            result.status = TestStatus.WARNING
            result.error = str(e)
            result.issues.append(f"State machine transitions test failed: {e}")
        
        result.duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        self.add_result(result)
    
    async def teardown(self):
        """Cleanup."""
        pass
