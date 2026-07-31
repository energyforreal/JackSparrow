"""Patch orchestrator prediction handler and remove legacy helpers."""

from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "agent" / "core" / "mcp_orchestrator.py"

NEW_HANDLE_PREDICTION = '''
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
            if (
                signal == "HOLD"
                and bar_idx is not None
                and self._last_entry_decision_bar == int(bar_idx)
            ):
                return
            if signal in _entry_signals and bar_idx is not None:
                bar_i = int(bar_idx)
                if self._last_entry_decision_bar == bar_i:
                    return
                self._last_entry_decision_bar = bar_i

            raw_model_predictions = result.get("model_predictions") or []
            model_predictions_for_reasoning = self._build_model_predictions_for_reasoning(
                raw_model_predictions
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
                    memory_context_count=0,
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

REMOVE_START = "    async def generate_reasoning("
REMOVE_END = "    async def _handle_prediction_request("


def main() -> None:
    text = ORCH.read_text(encoding="utf-8")
    start = text.index(REMOVE_START)
    end = text.index(REMOVE_END, start)
    text = text[:start] + NEW_HANDLE_PREDICTION + text[end + len(REMOVE_END) :]

    # Remove duplicate old _handle_prediction_request through _handle_reasoning_request
    old_start = text.index("    async def _handle_prediction_request(self, event: ModelPredictionRequestEvent):")
    # find second occurrence - we inserted new one, need to remove old block until persist_v43
    second = text.index(
        "    async def _handle_prediction_request(self, event: ModelPredictionRequestEvent):",
        old_start + 10,
    )
    third_marker = "    async def _persist_v43_gate_state_locked"
    if third_marker in text[second:]:
        third = text.index(third_marker, second)
        text = text[:second] + text[third:]

    # Stub v43 gate persistence methods
    gate_stub = '''
    async def _persist_v43_gate_state_locked(self, symbol: str) -> None:
        return None

    def note_v43_signal_decision(self, bar_index: int) -> None:
        return None

    def note_v43_entry_failed(self, bar_index: int) -> None:
        return None

    def note_v43_entry_executed(self, bar_index: int) -> None:
        return None

    async def persist_v43_gate_state_after_trade(self, symbol: str) -> None:
        return None

'''
    if "async def _persist_v43_gate_state_locked" in text:
        gstart = text.index("    async def _persist_v43_gate_state_locked")
        gend = text.index("\n\n# Global", gstart) if "\n\n# Global" in text[gstart:] else len(text)
        # find end of persist_v43_gate_state_after_trade method
        after_trade = text.index("    async def persist_v43_gate_state_after_trade", gstart)
        # find next def at class level after after_trade
        next_def = text.index("\n    async def ", after_trade + 5)
        text = text[:gstart] + gate_stub + text[next_def:]

    ORCH.write_text(text, encoding="utf-8")
    print("patched handlers")


if __name__ == "__main__":
    main()
