# HOLD Signal Dominance Diagnosis (Code-Traced)

This report explains why the trading agent predominantly produces `HOLD` signals instead of actionable `BUY`/`SELL`, using the actual runtime control flow and explicit numeric thresholds found in the code.

Training-context note: this diagnosis remains valid even when training uses expanded feature schemas and fee-aware TP/SL labels. HOLD dominance can still emerge from runtime consensus banding, disagreement damping, and execution gates independent of the training notebook choice.

---

## 1) Root Cause of HOLD-Dominant Behavior

### 1.1 The primary rule that produces `HOLD`: reasoning decision banding
The `MCPReasoningEngine` generates the final trading conclusion in `agent/core/reasoning_engine.py` inside `_step5_decision_synthesis()`. It computes a single scalar `consensus` (in `[-1, +1]`) from model predictions, then applies a volatility-adaptive band:

1. Compute `(strong_thresh, mild_thresh)` from `vol = features.get("volatility")`:
   - If `vol > 5`: `strong_thresh=0.75`, `mild_thresh=0.40`
   - If `vol < 1.5`: `strong_thresh=0.60`, `mild_thresh=0.25`
   - Else: `strong_thresh=0.70`, `mild_thresh=0.30`
2. Output logic:
   - `STRONG_BUY` if `consensus > strong_thresh`
   - `BUY` if `consensus > mild_thresh`
   - `STRONG_SELL` if `consensus < -strong_thresh`
   - `SELL` if `consensus < -mild_thresh`
   - **`HOLD` otherwise**

Therefore, `HOLD` happens whenever `consensus` falls within a *wide neutral band* around 0:
- `vol > 5`: `consensus ∈ [-0.40, +0.40]`
- `1.5 <= vol <= 5`: `consensus ∈ [-0.30, +0.30]`
- `vol < 1.5`: `consensus ∈ [-0.25, +0.25]`

This is the most direct “rule-driven” reason `HOLD` dominates: unless the consensus magnitude is large enough, the engine intentionally outputs `HOLD`.

### 1.2 Consensus is frequently shrunk toward 0 by disagreement damping
In `agent/core/reasoning_engine.py`, `_step3_model_consensus()` applies a “model disagreement filter”:
- It computes `pred_stdev` over per-model `prediction` values.
- If `pred_stdev > settings.model_disagreement_threshold` (default `0.4`), it multiplies consensus by:
  - `max(0.0, 1.0 - (pred_stdev - thresh))`

Whenever stdev exceeds `0.4`, consensus magnitude is reduced, making it more likely to fall back into the `_step5_decision_synthesis()` neutral `HOLD` band.

### 1.3 Even when models are confident, the v4 ensemble mapping can yield near-zero consensus
For the production discovery path, models are loaded via v4 metadata and executed by `agent/models/v4_ensemble_node.py` (`V4EnsembleNode`).

The v4 entry classifier produces:
- `entry_signal = buy_prob - sell_prob` (returned as `prediction` in MCP model output)
- `confidence = max(sell, hold, buy)`

This means:
- If the model assigns high probability mass to `HOLD` (or both `BUY` and `SELL` are similar), `buy_prob - sell_prob` becomes small.
- Small `consensus` then maps to `HOLD` in `_step5_decision_synthesis()`.

So the `HOLD` frequency is **both rule-driven** (wide `consensus` neutral band) and **model-driven** (neutral/near-zero consensus becomes likely under a “hold-heavy” class distribution).

### 1.4 Trading handler makes `HOLD` non-executable (so “actionable trades” vanish)
In `agent/events/handlers/trading_handler.py`, `TradingEventHandler.handle_decision_ready_for_trading()` hard-stops on:
- `if signal == "HOLD" or not signal: return`

So even if the system is correctly producing signals, any `HOLD` signal prevents risk approval and execution.

This is a second-order effect: it does not cause the *signal* to be `HOLD`, but it makes the *trading outcome* dominated by “no trade”.

---

## 1.1 Trading Style Validation (Scalping)

**Answer: NO — the current system is not scalping-ready.**

### Why it is not scalping
1. **Prediction horizon mismatch (training labels)**  
   v4 metadata explicitly configures forward lookahead for entry classification. For example, in `agent/model_storage/jacksparrow_v4_BTCUSD/metadata_BTCUSD_15m.json`:
   - `entry_lookahead: 4`
   - With `timeframe="15m"`, that is ~1 hour of forward horizon.
   This is not the short horizon typical of scalping (usually minutes).

2. **Profit/stop targets are too large for fees + microstructure**
   Defaults in `agent/core/config.py`:
   - `stop_loss_percentage = 0.02` (2%)
   - `take_profit_percentage = 0.05` (5%)
   Those are swing-trade magnitudes, not fee-overcoming scalping targets.

3. **Exit logic/monitoring is interval-based, not micro-tick driven**
   Position management occurs in the agent’s `_position_monitor_loop` at a configured interval (e.g. `position_monitor_interval_seconds`, default `15s`), not per micro price movement.

4. **Entry triggers are “major moves” driven, not every micro swing**
   `PRICE_FLUCTUATION_THRESHOLD_PCT` defaults to `0.5%`. The ML pipeline triggers mainly on that threshold in `agent/data/market_data_service.py`.

### Required changes to convert to scalping
1. Retrain models for a much shorter label lookahead (minutes-scale) and smaller threshold/targets appropriate for fee regimes.
2. Reduce `STOP_LOSS_PERCENTAGE` / `TAKE_PROFIT_PERCENTAGE` and/or recalibrate ATR multipliers used in `trading_handler.py`.
3. Make the signal decision and position management respond on the same micro-time scale (or at least close/open on shorter intervals than current `15s` monitoring and `0.5%` fluctuation triggers).

---

## 1.2 Feature Engineering Validation

### 1.2.1 Features actually used in prediction (v4 required feature set)
In the active v4 path, the model-required feature names come from v4 metadata, and the runtime requests exactly those via:
- `agent/events/handlers/market_data_handler.py` → `_get_runtime_feature_names()` → `mcp_orchestrator.model_registry.get_required_feature_names()`
- `agent/models/mcp_model_registry.py` → `get_required_feature_names()` unions `V4EnsembleNode.get_model_info()["features_required"]`

Example: for `metadata_BTCUSD_15m.json`, the v4 entry/exit feature set is exactly 18 features:
- `ema_9`, `ema_21`, `macd`, `macd_signal`, `atr_14`, `macd_hist`
- `adx_14`, `rsi_14`, `vol_zscore`, `vol_ratio`
- `bb_pct`, `bb_width`, `roc_20`, `roc_10`
- `ema_cross`, `returns_1`, `atr_pct`, `volatility_20`

### 1.2.2 Missing critical feature categories for short-term/scalping
Although the repo contains candlestick and chart-pattern feature engines in `feature_store/unified_feature_engine.py`, **those are not part of the v4 required feature list**, because v4 metadata does not request any `cdl_*` or `sr_*`/`tl_*`/`chp_*`/`bo_*` features.

So in the actual live prediction path:
- Candlestick patterns are **not explicitly captured** (no `cdl_` features requested).
- Support/resistance and breakout context are **not captured** (no `sr_`, `tl_`, `bo_`, etc. requested).

### 1.2.3 Train/live alignment risk (v4 formulas not provably identical)
The code path for v4 inference is fully defined (metadata + `V4EnsembleNode` + `FeatureEngineering` computations), but the v4 training implementation that produced the specific v4 artifacts is not present in this repo. As a result, parity between training-time feature math and runtime feature math cannot be guaranteed from repository code alone.

This can contribute to models outputting near-neutral consensus (which then maps to HOLD by the reasoning band).

---

## 1.3 Decision Drivers (End-to-End Trace)

### 1.3.1 Features → model outputs → reasoning conclusion
End-to-end decision flow (agent-side):

1. Market events trigger the ML pipeline:
   - `agent/data/market_data_service.py` emits `PriceFluctuationEvent` and `CandleClosedEvent`
2. `agent/events/handlers/market_data_handler.py` computes runtime `feature_names` from the model registry and publishes `FeatureRequestEvent`
3. `agent/data/feature_server.py` computes features and publishes `FeatureComputedEvent`
4. `agent/events/handlers/feature_handler.py` publishes `ModelPredictionRequestEvent`
5. `agent/core/mcp_orchestrator.py` handles the request, calls the model registry, then calls `MCPReasoningEngine.generate_reasoning()`
6. `agent/core/reasoning_engine.py` produces the final conclusion, and `_extract_decision_from_reasoning()` in `agent/core/mcp_orchestrator.py` maps it into:
   - `STRONG_BUY`, `BUY`, `STRONG_SELL`, `SELL`, or `HOLD`

### 1.3.2 Reasoning and trading suppressions of BUY/SELL
Even if the reasoning engine produces `BUY/SELL`, `trading_handler.py` can still suppress execution:
1. **Hard skip:** `signal == "HOLD"` returns immediately (no trade)
2. **Confidence gate:** rejects if `confidence < settings.min_confidence_threshold` (default `0.65`)
3. **Volatility presence gate:** rejects if `features.get("volatility") is None`
   - `mcp_orchestrator.py` derives `volatility` from `volatility_10` or `volatility_20` when needed
4. **ADX ranging filter:** blocks only mild `BUY/SELL` when:
   - `adx_14 is not None and adx_14 < 20 and signal in ("BUY","SELL")`
   - Strong signals are not blocked by this ADX rule
5. **Debounce:** deduplicates `(symbol, side)` approvals for `30s`

### 1.3.3 Points where BUY/SELL become “no actionable trade”
- If the *signal* itself is `HOLD`: the system never enters execution.
- If the *signal* is `BUY/SELL` but confidence/ADX/risk gates reject: no `RiskApprovedEvent` is published, so no trade is executed.

---

## 2) System Functionality Validation

### 2.1 Is the system functioning correctly?
**PARTIAL — the pipeline is implemented correctly, but HOLD dominance can be produced by the decision rules and/or degraded model outputs.**

### 2.2 Verified pipeline checkpoints from code (where to instrument)
To confirm whether HOLD is produced at the “decision stage” or after “trade gating”, check these event points:
1. `CandleClosedEvent` / `PriceFluctuationEvent` emission:
   - `agent/data/market_data_service.py` (`_on_candle_close`, `_on_price_fluctuation`)
2. `FeatureRequestEvent` / `FeatureComputedEvent`:
   - `agent/events/handlers/market_data_handler.py`
   - `agent/data/feature_server.py` (`_emit_feature_computed_event`)
3. `ModelPredictionCompleteEvent` and `DecisionReadyEvent`:
   - `agent/core/mcp_orchestrator.py` publishes `DecisionReadyEvent` when `process_prediction_request()` succeeds
4. Trading gate at `DecisionReadyEvent` consumer:
   - `agent/events/handlers/trading_handler.py` logs rejection reasons via `_log_entry_rejected()`

### 2.3 Failure modes that can yield persistent HOLD
1. If model nodes return predictions with `prediction=0.0` and `confidence=0.0` (e.g., inference exceptions), `_step5_decision_synthesis()` will see consensus near 0 and output `HOLD`.
2. If event messages arrive but trading handler rejects (confidence < 0.65, missing volatility, stale signal, ADX < 20 for mild signals), then executed trades will be rare even if non-HOLD signals occur.

To distinguish these, you must compare:
- `DecisionReadyEvent.payload.signal` vs
- presence of `RiskApprovedEvent` and resulting `OrderFillEvent`.

---

## 3) Final Answers (Required Output)

1. **Root cause of HOLD-dominant behavior**  
   The reasoning engine’s `_step5_decision_synthesis()` intentionally outputs `HOLD` whenever consensus is inside a broad volatility-adaptive neutral band (e.g. `[-0.30, +0.30]` for typical volatility). Consensus magnitude is additionally reduced by `_step3_model_consensus()` disagreement damping. The trading handler then hard-skips `HOLD` signals, preventing execution.

2. **Whether the system supports scalping trading (YES/NO)**  
   **NO.** The model label horizon (e.g. v4 `entry_lookahead=4` for `15m`), the profit/stop defaults (2%/5%), and the monitoring/trigger cadence are not scalping-aligned.

3. **Feature engineering effectiveness analysis**  
   Live inference uses v4-required features (18 indicators such as EMAs, MACD, ADX, RSI, ATR, BB, ROC, volatility measures). Candlestick and chart-pattern features exist in the engine but are not requested by v4 metadata, so microstructure and market-structure features (support/resistance, breakout flags) are missing.

4. **Trade decision logic breakdown**  
   `Features` → `Model predictions (prediction, confidence)` → `MCPReasoningEngine` consensus band → `DecisionReadyEvent.signal` → `TradingEventHandler` gates:
   - skip `HOLD`
   - require `confidence >= min_confidence_threshold` (default `0.65`)
   - require `features.volatility`
   - ADX ranging filter blocks mild `BUY/SELL` when `adx_14 < 20`
   - debounce and risk validation final gate

5. **System health status (YES/PARTIAL/NO)**  
   **PARTIAL.** The architecture and event chain are present, but HOLD dominance is expected given the decision band and can be amplified by degraded model outputs (zero confidence/predictions) or trade-gating rejections.

6. **Top 5 critical issues**
   1. Wide `HOLD` neutral band in `MCPReasoningEngine._step5_decision_synthesis()` that frequently classifies neutral consensus as `HOLD`.
   2. Consensus dampening in `_step3_model_consensus()` that shrinks predictions toward 0 when models disagree, increasing probability of `HOLD`.
   3. v4 model mapping uses `prediction = buy_prob - sell_prob`; if the ensemble is frequently assigning mass to `HOLD`, consensus stays near 0.
   4. Trading handler hard-skips `HOLD` signals, so any `HOLD` decision fully blocks execution.
   5. v4 required feature set omits candlestick and support/resistance/chart-context features that are typically useful for scalping/short-term edge detection.

7. **Top 5 high-impact fixes**
   1. Narrow or reparameterize the `HOLD` band in `_step5_decision_synthesis()` (e.g., reduce mild thresholds, or require additional evidence like confidence/ADX/volatility alignment before using banding).
   2. Reduce aggressiveness of disagreement dampening in `_step3_model_consensus()` (or make it confidence-aware) so consensus is not routinely pulled into the `HOLD` region.
   3. Change the v4 decision rule to use probability-based thresholds (e.g., require `buy_prob > X` and `sell_prob < Y`) rather than only `buy_prob - sell_prob`.
   4. Align `min_confidence_threshold` with the actual calibration scale of `final_confidence` produced by `_step6_confidence_calibration()`; otherwise non-HOLD signals may still never become executions.
   5. Add scalping-relevant features into the live required feature set (enable/request `cdl_*` and chart-context features) or create a separate short-horizon model family with appropriate labels and SL/TP targets.

