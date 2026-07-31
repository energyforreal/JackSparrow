"""Final orchestrator cleanup via string markers."""

from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "agent" / "core" / "mcp_orchestrator.py"

SLIM_HEALTH = '''
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

'''

NEW_HANDLER = '''
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

'''

GATE_STUBS = '''
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

'''


def main() -> None:
    text = ORCH.read_text(encoding="utf-8")

    g1 = text.index("    async def generate_reasoning(")
    g2 = text.index("    def _get_required_features(", g1)
    text = text[:g1] + text[g2:]

    f1 = text.index("    def _build_fast_hold_reasoning_chain(")
    f2 = text.index("    def _create_empty_prediction_response(", f1)
    text = text[:f1] + text[f2:]

    e1 = text.index("    async def _enrich_decision_event_self_awareness(")
    e2 = text.index("    async def get_health_status(", e1)
    h2 = text.index("    def _schedule_prediction_audit(", e2)
    text = text[:e1] + SLIM_HEALTH + text[h2:]

    p1 = text.index("    async def _handle_prediction_request(")
    p2 = text.index("    async def _persist_v43_gate_state_locked(", p1)
    text = text[:p1] + NEW_HANDLER + GATE_STUBS + text[p2:]

    g_start = text.index("    async def _persist_v43_gate_state_locked(", p1)
    g_end = text.index("\n\n# Create global MCP orchestrator instance")
    text = text[:g_start] + GATE_STUBS + text[g_end:]

    ORCH.write_text(text, encoding="utf-8")
    print("ok", ORCH)


if __name__ == "__main__":
    main()
