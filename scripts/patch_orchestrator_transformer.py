"""Patch mcp_orchestrator to use transformer-only prediction path."""

from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "agent" / "core" / "mcp_orchestrator.py"

NEW_METHOD = """
    async def _process_transformer_prediction(
        self,
        symbol: str,
        context: Dict[str, Any],
        _t0: float,
    ) -> Dict[str, Any]:
        \"\"\"Transformer-only path: frames -> ONNX -> threshold -> decision.\"\"\"
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

"""


def main() -> None:
    text = ORCH.read_text(encoding="utf-8")
    start = text.index("    async def _process_jacksparrow_v43_prediction(")
    end = text.index("    async def process_prediction_request(", start)
    text = text[:start] + NEW_METHOD + text[end:]
    text = text.replace(
        "return await self._process_jacksparrow_v43_prediction(symbol, context, _t0)",
        "return await self._process_transformer_prediction(symbol, context, _t0)",
    )
    ORCH.write_text(text, encoding="utf-8")
    print("patched", ORCH)


if __name__ == "__main__":
    main()
