"""Second-pass patch: simplify orchestrator init and decision emit."""

from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "agent" / "core" / "mcp_orchestrator.py"

REPLACEMENTS = [
    (
        """from agent.core.reasoning_engine import MCPReasoningEngine, MCPReasoningRequest, MCPReasoningChain
from agent.memory.vector_store import VectorMemoryStore, DecisionContext
from agent.events.event_bus import event_bus
from agent.events.schemas import (
    ModelPredictionRequestEvent,
    ModelPredictionCompleteEvent,
    ReasoningRequestEvent,
    ReasoningCompleteEvent,
    DecisionReadyEvent,
    EvidenceReadyEvent,
    EventType,
    PolicyAuthority,
    PolicyVerdict,
    MLEvidenceSnapshot,
)
from agent.core.agent_policy_engine import (
    agent_policy_engine,
    build_ml_evidence_from_orchestrator_result,
    build_ml_evidence_from_reasoning_context,
)
from agent.core.config import settings
from agent.core.agent_introspection import build_introspection_snapshot
from agent.core.v43_market_frames import closed_5m_bar_index
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
from feature_store.jacksparrow_v43_multihead import primary_execution_horizon_bars""",
        """from agent.memory.vector_store import VectorMemoryStore, DecisionContext
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
from feature_store.feature_registry import get_feature_list""",
    ),
    (
        """        self.reasoning_engine: Optional[MCPReasoningEngine] = None
        self.vector_store: Optional[VectorMemoryStore] = None
        self._required_feature_names_cache: List[str] = []
        self.delta_client = None  # Set by agent for 15m trend (MTF confirmation)
        self._initialized = False
        self._v43_gate_state = V43GateState()
        self._v43_gate_state_lock = asyncio.Lock()
        self._v43_gate_symbol: Optional[str] = None
        self._v43_last_entry_decision_bar: Optional[int] = None""",
        """        self.vector_store: Optional[VectorMemoryStore] = None
        self._required_feature_names_cache: List[str] = []
        self.delta_client = None
        self._initialized = False
        self._last_entry_decision_bar: Optional[int] = None""",
    ),
    (
        """                        discovery_mode="rule_based_ic",
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
                    )""",
        """                        discovery_mode="transformer",
                        message=(
                            "No transformer model loaded during initialization with "
                            "require_models_on_startup=True."
                        ),
                    )
                    raise RuntimeError(
                        "MCP Orchestrator initialization failed: no transformer model loaded."
                    )
                else:
                    logger.warning(
                        "mcp_orchestrator_no_models_loaded_monitoring_mode",
                        discovered_count=len(discovered_models),
                        discovery_mode="transformer",
                        message=(
                            "No transformer model loaded and require_models_on_startup=False. "
                            "Agent will continue in monitoring mode until MODEL_DIR bundle is valid."
                        ),
                    )""",
    ),
]

INIT_OLD = """            # Initialize Vector Memory Store for historical context retrieval (Step 2)
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
            event_bus.subscribe(EventType.REASONING_REQUEST, self._handle_reasoning_request)

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
                logger.warning("v43_gate_state_load_skipped", error=str(e))"""

INIT_NEW = """            from agent.memory.vector_store_factory import create_vector_store

            self.vector_store = await create_vector_store()

            event_bus.subscribe(EventType.MODEL_PREDICTION_REQUEST, self._handle_prediction_request)"""

SHUTDOWN_OLD = """            if self.reasoning_engine:
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
                    logger.warning("v43_gate_state_persist_on_shutdown_failed", error=str(e))"""

SHUTDOWN_NEW = """            if self.vector_store:
                await self.vector_store.shutdown()
                self.vector_store = None

            if self.model_registry:
                await self.model_registry.shutdown()

            if self.feature_server:
                await self.feature_server.shutdown()"""


def main() -> None:
    text = ORCH.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        if old not in text:
            raise SystemExit(f"missing block: {old[:80]}...")
        text = text.replace(old, new, 1)
    for old, new in [(INIT_OLD, INIT_NEW), (SHUTDOWN_OLD, SHUTDOWN_NEW)]:
        if old not in text:
            raise SystemExit(f"missing init/shutdown block: {old[:80]}...")
        text = text.replace(old, new, 1)
    ORCH.write_text(text, encoding="utf-8")
    print("patched orchestrator init/imports")


if __name__ == "__main__":
    main()
