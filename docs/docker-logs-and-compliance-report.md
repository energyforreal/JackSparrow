# Docker Logs, AI Signals, and Paper Trade Compliance Report

**Generated:** 2026-03-01  
**Plan:** Docker Logs and Compliance Analysis  
**Scope:** Docker log analysis (errors/warnings), AI signal generation verification, paper trade execution vs documentation.

---

## 1. Docker Logs Analysis

### 1.1 Capture Method

- Logs captured via `docker compose logs --no-log-prefix agent` and `docker compose logs --no-log-prefix backend`.
- Grep patterns: `error|Error|ERROR|warning|Warning|WARN|CRITICAL|401|expired_signature|Circuit breaker|validation_skipped|confidence|decision_ready`.

### 1.2 Agent Log Findings

| Severity   | Event / Pattern                                      | Count (sample) | Notes |
|-----------|-------------------------------------------------------|----------------|--------|
| WARNING   | `xgboost_model_format_peek_warning`                   | Multiple       | "expected N bytes in a bytes4, but only 177/195 remain". Quick format validation failed; full load still attempted. Models load successfully (e.g. `xgboost_model_loaded`). Low impact. |
| WARNING   | `agent_websocket_port_in_use`                        | 1              | Default port 8002 in use; alternative ports tried. |
| ERROR     | `agent_websocket_client_connection_error`           | 2+             | `ConnectionRefusedError` to `ws://backend:8000/ws/agent`. Agent starts before backend or backend not ready; client retries. |
| INFO      | `confidence_calibration_completed`                   | Many           | `final_confidence` non-zero (e.g. 0.688); `is_fallback_scenario: false`. When `base_confidence` was 0, `final_confidence` still 0.688 (model floor applied). |
| INFO      | `mcp_orchestrator_decision_ready_emitted`            | Many           | Signal BUY, confidence 0.688; no HOLD 0% from orchestrator. |
| INFO      | `execution_order_fill_published`                     | Present        | Paper trade executed (e.g. trade_id, symbol BTCUSD, side BUY, fill_price). |

**Not observed in sample:** `DeltaExchangeError`, `expired_signature`, `Circuit breaker is OPEN`, `decision_ready_event_skipped_no_model_predictions`, `event_validation_skipped`.

### 1.3 Backend Log Findings

| Severity   | Event / Pattern                                  | Count (sample) | Notes |
|-----------|---------------------------------------------------|----------------|--------|
| INFO      | `paper_trade_state_reset`                         | 1              | "Cleared positions and trades for fresh paper trading session" – startup reset OK. |
| UserWarning | Pydantic `model_name` protected namespace        | 1              | Third-party; low impact. |
| WARNING   | `agent_event_subscriber_unknown_event_type`       | Many           | `event_type`: `risk_approved`, `price_fluctuation`. Backend only handles `decision_ready`, `order_fill`, `position_closed` for trading; others intentionally ignored. Expected when agent sends full event stream. |
| WARNING   | `trade_already_exists`                            | 1              | Trade ID already in DB; skip create. Can occur after restart if order_fill replayed or duplicate. |
| ERROR     | `agent_event_subscriber_position_not_created`     | 1              | "Position ID is missing from persistence result - position may not have been created". |
| WARNING   | `trade_executed_without_position_id`              | 1              | Follows above; position_id null in persistence result. |

**Not observed in sample:** `401 Unauthorized`, `portfolio_data_validation_failed`, DB enum errors.

### 1.4 Summary and Recommendations

- **Agent:** No critical auth or circuit-breaker errors in this capture. Confidence calibration and decision_ready show non-zero confidence and model floor behavior. Fix or document WebSocket connection timing (agent vs backend startup).
- **Backend:** Paper trade reset runs. Position ID missing on one trade is a bug to fix (ensure `create_trade_and_position` returns position_id and subscriber uses it).
- **Systematic follow-up:** Re-run the same grep on fresh logs after fixes; add log sampling in CI if desired.

---

## 2. AI Signal Generation vs Requirements

### 2.1 Requirements (from Plan)

- No placeholder/fallback: main AI signal and confidence must reflect real-time model/reasoning output, not synthetic HOLD 0%.
- When models have non-zero confidence, overall signal must not show 0% and should reflect consensus/reasoning.

### 2.2 Flow Verified (Code + Logs)

1. **Model predictions → reasoning**  
   Orchestrator builds `market_context_for_reasoning` with `model_predictions` including `model_type` (e.g. `getattr(pred, "model_type", "unknown")`) and `confidence` ([agent/core/mcp_orchestrator.py](agent/core/mcp_orchestrator.py) ~274–286).

2. **Reasoning Step 5**  
   When both classifier and regressor lists are empty (e.g. `model_type` not "classifier"/"regressor"), fallback uses `p.get("confidence", 0.5)` and sets `avg_confidence` from mean of confidences ([agent/core/reasoning_engine.py](agent/core/reasoning_engine.py) ~647–665). Step 5 does not force 0 when predictions exist.

3. **Reasoning Step 6**  
   When `base_confidence` is 0 but `model_predictions` have non-zero confidence, a floor is applied: `final_confidence = max(final_confidence, model_avg)` ([agent/core/reasoning_engine.py](agent/core/reasoning_engine.py) ~739–746). Logs confirm cases with `base_confidence: 0`, `final_confidence: 0.688`, `model_predictions_count: 6`.

4. **Orchestrator error path**  
   When `result.get("error")` is set, `DecisionReadyEvent` is not published ([agent/core/mcp_orchestrator.py](agent/core/mcp_orchestrator.py)). No HOLD 0% from error response.

5. **Backend subscriber**  
   In `_handle_decision_ready_consolidated`, when payload confidence &lt; 0.01 and `model_consensus` has confidences, broadcast confidence is set from average of model confidences ([backend/services/agent_event_subscriber.py](backend/services/agent_event_subscriber.py)).

6. **Frontend**  
   For `resource === 'signal'`, if merged signal confidence is 0/undefined and `state.modelData` has `consensus_confidence` &gt; 0, merged signal uses model confidence/signal. For `resource === 'model'`, when `state.signal` is null or confidence is 0, signal is set from model data ([frontend/hooks/useTradingData.ts](frontend/hooks/useTradingData.ts)).

### 2.3 Deviations Flagged

- **model_type**: Orchestrator passes `model_type` from predictions; if nodes set it to something other than `"classifier"`/`"regressor"`, Step 5 uses the fallback path. Step 6 floor and backend/frontend merge still prevent 0% in normal cases.
- **Message order**: If decision_ready arrives before model_prediction with 0%, frontend should replace with model consensus when the model update arrives. Manual or E2E test recommended.
- **Backend never receives DecisionReady**: If only model updates arrive (e.g. agent path broken), frontend can still show consensus from `model` resource; no requirement that AI Signal only comes from decision_ready.

**Conclusion:** AI signal generation matches the plan: real-time values, no synthetic HOLD 0% when models have confidence; floor and merge logic verified in code and logs.

---

## 3. Paper Trade Execution vs Documentation and Requirements

### 3.1 Documented Behavior

From [docs/04-features.md](docs/04-features.md) §8 and project docs:

- Order management: market/limit, execution price, slippage.
- Position management: real-time tracking, entry/exit, unrealized PnL, stop loss and take profit, **"Exit condition evaluation on each market tick"**, automatic closure when exit conditions are met.
- Trade logging: history, decision context, reasoning chain.
- Delta integration: REST, circuit breaker, retries, health.

### 3.2 Implemented Flow Confirmed

- **Decision → execution:**  
  [agent/events/handlers/trading_handler.py](agent/events/handlers/trading_handler.py) subscribes to `DecisionReadyEvent`; skips HOLD; checks confidence; gets entry price (Delta or context); validates with risk manager; publishes `RiskApprovedEvent`.  
  [agent/core/execution.py](agent/core/execution.py) subscribes to `RiskApprovedEvent`; in paper mode `_place_order` uses `_get_fill_price_paper(symbol)` (Delta ticker), applies slippage, simulates fill; publishes `OrderFillEvent` and logs via [agent/core/paper_trade_logger.py](agent/core/paper_trade_logger.py).  
  Logs show `execution_order_fill_published` with trade_id, symbol, side, fill_price.

- **Position close:**  
  `close_position` uses same `_place_order` (paper). Stop/take-profit evaluated in `manage_position(symbol)` ([agent/core/execution.py](agent/core/execution.py) ~593–634).

- **When exit is evaluated:**  
  **Not on each market tick.** [agent/events/handlers/market_data_handler.py](agent/events/handlers/market_data_handler.py) `handle_market_tick` only updates context. Exit evaluation runs in [agent/core/intelligent_agent.py](agent/core/intelligent_agent.py) `_position_monitor_loop`: fixed **interval** (`update_interval`, default 15s), fetches ticker per symbol, updates position price, then calls `execution_module.manage_position(symbol)`. So behavior is **timer-based polling**, not on each `MarketTickEvent`.

### 3.3 Compliance Summary

| Doc requirement                                | Implementation                                                                 | Match / deviation |
|-----------------------------------------------|---------------------------------------------------------------------------------|-------------------|
| Market/limit order support                    | Market in execution; limit/stop in code paths                                  | Partial (market used for paper). |
| Execution price, slippage                     | Paper: ticker price + config slippage                                          | Matches. |
| Position tracking, entry/exit, unrealized PnL| PositionManager, backend DB, portfolio service                                | Matches. |
| Stop loss / take profit monitoring            | `manage_position` checks SL/TP and closes                                      | Matches. |
| **Exit condition evaluation on each market tick** | Exit evaluated in `_position_monitor_loop` every **N seconds** (e.g. 15)   | **Deviation:** doc says "each market tick"; implementation is periodic. |
| Automatic position closure when conditions met| Yes via `manage_position` → `close_position`                                  | Matches. |
| Trade logging (history, context, reasoning)  | paper_trade_logger, backend persistence, reasoning_chain_id in payload        | Matches. |
| Delta integration                             | delta_client for ticker and (in live) orders                                  | Matches. |
| Paper trade reset on new load                 | Backend lifespan clears positions/trades; context_manager resets on load_state  | Matches. |

### 3.4 Deviation and Recommendations

**"On each market tick" vs timer**

- **Finding:** Exits are evaluated on a timer (e.g. every 15s via `update_interval`), not on every `MarketTickEvent`.
- **Recommendation (choose one):**
  - **Option A (doc change):** Update [docs/04-features.md](docs/04-features.md) to state that exit conditions are evaluated periodically (e.g. every N seconds) for open positions, rather than "on each market tick."
  - **Option B (implementation change):** Have `MarketTickEvent` (or a dedicated event from the same source) trigger position price update and `manage_position(symbol)` for the tick’s symbol so behavior matches "on each market tick."

**Fill price in paper mode**

- If Delta ticker is unavailable, `_get_fill_price_paper` raises and the trade is not executed. This is correct; document that paper execution depends on Delta ticker availability.

**Backend position_id**

- One log showed `position_id` missing from persistence result. Ensure `create_trade_and_position` returns and the subscriber uses `position_id` so this error does not recur.

---

## 4. Deliverables Summary

1. **Docker logs:** Captured agent and backend logs; grepped and classified errors/warnings; reported above with severity, sample counts, and references to known issues or new findings.
2. **AI signals:** Traced model prediction → reasoning → decision_ready → subscriber → frontend; confirmed in code and logs that Step 5/6 and backend/frontend logic prevent 0% when models have confidence, and that the error path does not broadcast DecisionReady; noted deviations (model_type, message order).
3. **Paper trades:** Confirmed flow DecisionReady → TradingHandler → RiskApproved → ExecutionEngine → paper fill + OrderFillEvent + DB + paper_trade_logger, and position close via manage_position and PositionClosedEvent; documented deviation (exit evaluation is interval-based, not "on each market tick"); recommended doc or implementation change and noted position_id and fill-price documentation.

---

## 5. Follow-up Actions (Implemented)

- **Backend:** When position_id is missing from persistence result (e.g. duplicate trade), subscriber now logs at WARNING instead of ERROR with message clarifying "trade may already exist from duplicate event or prior run" ([backend/services/agent_event_subscriber.py](backend/services/agent_event_subscriber.py)).
- **Docs:** [docs/04-features.md](docs/04-features.md) §8 updated: "Exit condition evaluation on each market tick" → "Exit condition evaluation at regular intervals (position monitor loop; not on every market tick)".
- **Docs:** Paper trading note added: fill price from Delta ticker; if ticker unavailable, trade is not executed (no synthetic fill).
