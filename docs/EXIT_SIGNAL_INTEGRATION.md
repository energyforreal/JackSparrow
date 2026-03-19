## v4 Entry/Exit Signal Integration

- **v4 ensemble outputs** (see `agent/models/v4_ensemble_node.py`):
  - Computes an **entry signal** in \[-1, +1\] from the 3-class entry model (`SELL`, `HOLD`, `BUY`).
  - Computes an **exit signal** in \[-1, +1\] from the 2-class exit model (`HOLD`, `EXIT`).
  - Returns `prediction=entry_signal` and exposes `exit_signal` in the prediction `context`:
    - `context["entry_signal"]`, `context["exit_signal"]`
    - `context["entry_proba"]`, `context["exit_proba"]`

- **Consensus and trading decision**:
  - `MCPModelRegistry` (`agent/models/mcp_model_registry.py`) aggregates **entry signals only** into a single continuous consensus prediction.
  - `MCPOrchestrator` (`agent/core/mcp_orchestrator.py`) turns that consensus into a discrete trading **signal** (`BUY/SELL/STRONG_*` or `HOLD`) and `position_size`.
  - The orchestrator embeds per-model contexts (including `exit_signal`) into `market_context` for downstream consumers.

- **How exits are currently triggered**:
  - `trading_handler` (`agent/events/handlers/trading_handler.py`) listens to `DecisionReadyEvent` payloads with:
    - `signal` (BUY/SELL/STRONG_* / HOLD)
    - `reasoning_chain.market_context`, which may contain `features` and model-level context (including `exit_signal` in model prediction contexts).
  - Position exits today are driven by:
    - **Signal reversal exits** (`signal_reversal_exit`) when a new signal contradicts an open position.
    - **Risk-based exits** (stop-loss, take-profit, time-limit) implemented in `agent/core/execution.py` and `agent/core/risk_manager.py`.
  - The v4 **exit_signal** is not yet wired as a direct hard trigger for closing positions; instead, it is available in the prediction context for future strategies and UI.

- **Implications**:
  - Entry models directly influence **position entry and direction** via consensus.
  - Exit models currently influence behavior **indirectly**, via the additional exit context available to reasoning and any custom analytics, but not as a standalone \"force close\" rule.
  - Future enhancements can promote `exit_signal` to an explicit exit rule in `trading_handler` or `execution` (for example, closing or tightening stops when `exit_signal` crosses a threshold), without changing the v4 model interface.

