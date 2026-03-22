# JackSparrow – Implementation Error Analysis
**Scope**: Paper Trading Logic · ML Signal Generation · Agent Interpretation  
**Source documents reviewed**: 01-architecture.md, 03-ml-models.md, 04-features.md, 05-logic-reasoning.md, 06-backend.md, Paper_Trading_ML_Signals_and_Exec.txt

---

## Summary of Findings

| # | Category | Severity | Description |
|---|----------|----------|-------------|
| 1 | ML Signal Generation | 🔴 Critical | Classifier normalization is wrong for 3-class output |
| 2 | Paper Trading | 🔴 Critical | Stop-loss exits may be blocked by the debounce + risk/reward gate |
| 3 | Paper Trading | 🔴 Critical | Feature count mismatch (49 trained vs 50 at runtime) |
| 4 | ML Signal Generation | 🟠 High | Consensus `agreement` formula produces values outside [0,1] without clamping nuance |
| 5 | ML Signal Generation | 🟠 High | Confidence is zero for a unanimous HOLD signal |
| 6 | Agent Interpretation | 🟠 High | Dual exit paths described — one blocks the other |
| 7 | Agent Interpretation | 🟠 High | Position monitor is timer-based (15s) but exit architecture promises tick-based |
| 8 | ML Signal Generation | 🟡 Medium | Regressor return normalization cap (±10%) too tight for BTC |
| 9 | Agent Interpretation | 🟡 Medium | Signal threshold (>0.3 = BUY) contradicts documented 60% consensus requirement |
| 10 | Agent Interpretation | 🟡 Medium | Confidence calibration formula (simple average) is statistically unsound |
| 11 | Paper Trading | 🟡 Medium | Slippage formula applies constant 50% magnitude, not random |
| 12 | Agent Interpretation | 🟡 Medium | Learning disabled → Step 6 always applies a flat 20% confidence penalty |
| 13 | ML Signal Generation | 🟡 Medium | `ModelPerformanceTracker` uses continuous-error metric for classifier predictions |
| 14 | Paper Trading | 🟡 Medium | Close + reopen uses single ticker snapshot — double slippage not simulated |
| 15 | Architecture | 🔵 Low | Training script saves models without `_classifier`/`_regressor` suffix |

---

## 1 🔴 Classifier Normalization Wrong for 3-Class Output

**Location**: `03-ml-models.md` – Normalization section for XGBoost Classifier

**Documented normalization**:
```python
# Probability output [0, 1] → [-1, 1]
normalized = (probability - 0.5) * 2.0

# Class label → [-1, 1]
normalized = (label * 2.0) - 1.0
```

**Problem — class label formula**:  
Training labels are `{-1 (SELL), 0 (HOLD), 1 (BUY)}`. Applying `(label * 2.0) - 1.0`:

| Raw label | Result |
|-----------|--------|
| -1 | **-3.0** ← out of [-1, 1] range |
| 0 | -1.0 |
| 1 | 1.0 |

A SELL label produces -3.0, which after consensus weighting could push the aggregate consensus far below -1.0 and distort any subsequent threshold logic.

**Problem — probability formula**:  
`predict_proba()` for a 3-class model returns `[P(SELL), P(HOLD), P(BUY)]`. The formula `(probability - 0.5) * 2.0` works only for binary classifiers. For 3-class output the correct signed signal is:

```python
# Correct approach for 3-class classifier
normalized = probabilities[BUY_INDEX] - probabilities[SELL_INDEX]
# Result is naturally in [-1, +1]
```

Using the raw probability from a single (unspecified) class slot as a drop-in for a binary probability will generate incorrect signals for any multi-class model.

**Fix**: Replace the label and probability normalization functions in the XGBoost node with class-aware logic that computes `P(BUY) - P(SELL)` from `predict_proba()` and validates label range before applying the formula.

---

## 2 🔴 Stop-Loss Exits May Be Blocked by the TradingEventHandler Pipeline

**Location**: `05-logic-reasoning.md` (exit via `_handle_market_tick` → `DecisionReadyEvent`) vs `Paper_Trading…txt` Section 4.2

**Architecture doc** describes exits as:
> "Risk manager emits a `DecisionReadyEvent` with exit signal → High confidence (1.0) is assigned to exit decisions → Execution module closes position"

If exit `DecisionReadyEvent` is routed through `TradingEventHandler` (the same handler used for entries), it encounters:

1. **Confidence gate** — passes at 1.0 ✓  
2. **Debounce** — `one RiskApproved per (symbol, side) per 30s`. A position entered within the last 30 seconds will have its **stop-loss exit blocked** for the remainder of that window.  
3. **Risk/reward gate** — `reward/risk ≥ 1.2`. A stop-loss hit by definition has a negative reward/risk ratio, so **this gate will block every stop-loss exit that goes through TradingEventHandler**.

The technical report describes a separate path via `ExecutionEngine.manage_position()` that does NOT go through `TradingEventHandler`, but the architecture documentation describes the risk-manager path. If both exist, they may race each other. If only the risk-manager path exists, stop-losses are silently blocked.

**Fix**: Exit signals must bypass the entry gate filters (debounce, risk/reward). Either route them through a dedicated exit handler, or tag the `DecisionReadyEvent` as an exit and skip the non-applicable filters.

---

## 3 🔴 Feature Count Mismatch: Models Trained on 49, Runtime Sends 50

**Location**: `03-ml-models.md` (training script section) vs `01-architecture.md` / `Paper_Trading…txt`

The training documentation explicitly states: *"Computes all 49 technical indicators/features"* and the feature breakdown sums to 49:  
15 price + 10 momentum + 8 trend + 8 volatility + 6 volume + 2 returns = **49**

The runtime pipeline sends **50 features**:  
- Architecture doc: "FeatureRequestEvent with a fixed list of feature_names (50 features)"  
- Technical report: "50 features: SMA/EMA, RSI, MACD, volatility, volume, returns"

XGBoost will throw a feature count mismatch error at inference time unless the model was retrained with 50 features. The discrepancy suggests one of these is out of date and was never reconciled.

**Fix**: Audit the feature server's computed feature list and the training script. Align them to one canonical count (likely 50 if a feature was added post-training). Retrain models if necessary and update all documentation references.

---

## 4 🟠 Consensus `agreement` Formula Produces Misleading Values

**Location**: `05-logic-reasoning.md` – Model Consensus Mechanism

```python
agreement = 1.0 - np.std(predictions_array)
agreement = max(0.0, min(1.0, agreement))
```

For predictions in [-1, 1], `np.std` can reach ~1.0 (e.g., half models at -1, half at +1), causing `agreement` to reach 0 only at maximum disagreement. However:

- If all models agree at **0.5**, std = 0, agreement = **1.0** — but this represents weak signal agreement, not strong.  
- If all models agree at **0.0** (HOLD), std = 0, agreement = **1.0** — this feeds into Issue #5 (confidence = 0).  
- The raw std formula is not normalized to a theoretical maximum, so agreement doesn't smoothly scale with meaningful disagreement bounds.

A more reliable formula: `agreement = max(0, 1 - std / 1.0)` is identical for this range — the real issue is that std should be measured relative to the signal magnitude, not standalone.

**Fix**: Use `agreement = 1.0 - (np.std(predictions_array) / max_possible_std)` or re-define agreement as the fraction of predictions within a tolerance band around the consensus value.

---

## 5 🟠 Confidence = 0 for a Unanimous HOLD Signal

**Location**: `05-logic-reasoning.md`

```python
"confidence": agreement * abs(consensus_value)
```

If all 6 models unanimously predict HOLD (consensus_value = 0.0), then:  
`confidence = 1.0 × |0.0| = 0.0`

The UI will display 0% confidence for a fully unanimous HOLD — which is misleading and causes the confidence floor workaround mentioned in the technical report to be applied as a hack rather than a structural fix.

Additionally, the confidence gate in `TradingEventHandler` checks `confidence ≥ min_confidence_threshold`. A HOLD signal won't be traded, but the zero confidence will still propagate into the reasoning chain and mislead the Step 6 calibration calculation.

**Fix**: Separate "decision confidence" from "consensus signal strength". HOLD confidence should be measured as the agreement level itself, not as `agreement × |consensus|`.

---

## 6 🟠 Dual Exit Paths — Architecture Contradiction

**Location**: `05-logic-reasoning.md` vs `Paper_Trading…txt` Section 4.2

Two different exit mechanisms are described and appear to be implemented concurrently:

| Path | Source | Mechanism |
|------|--------|-----------|
| A | `05-logic-reasoning.md` | `_handle_market_tick()` in RiskManager → `DecisionReadyEvent` → TradingEventHandler → RiskApprovedEvent → ExecutionEngine |
| B | `Paper_Trading…txt` | `ExecutionEngine.manage_position()` polls every 15s → directly calls `close_position()` |

If both paths are active:
- Path A fires on every market tick for each open position.
- Path B fires every 15 seconds.
- If both detect a stop-loss simultaneously, `close_position()` will be called twice → double-close error or orphaned position state.

**Fix**: Choose one canonical exit path and document it clearly. Given the risk of Path A blocking exits (Issue #2), Path B (direct `manage_position()`) is safer but needs to be confirmed as the authoritative mechanism. Remove or clearly subordinate the other.

---

## 7 🟠 Position Monitor is Timer-Based (15s) — Not Tick-Based as Documented

**Location**: `Paper_Trading…txt` Section 4.3 vs `01-architecture.md` Exit Flow

The technical report confirms: *"A position monitor loop... runs periodically (e.g. every 15s)"*.

The architecture exit flow states: *"Market Data Service → Emit MarketTickEvent on price updates → Risk Manager → Check exit conditions"* — implying near real-time exit monitoring.

In a 15-second polling model:
- BTC can move 0.3–0.5%+ in 15 seconds during volatility.
- A stop-loss set at -2% could be breached, continue falling, and the position closes at -2.3% or worse.
- In paper trading, the fill price is taken from `get_ticker()` at the time `manage_position()` runs, not at the actual stop price — leading to inaccurate P&L simulation.

**Fix**: Either implement tick-based exit evaluation (subscribe to `PriceFluctuationEvent` in position monitor), or document that the 15s polling introduces exit price slippage and adjust P&L reporting accordingly.

---

## 8 🟡 Regressor Normalization Cap (±10%) Is Too Tight for BTC

**Location**: `03-ml-models.md` – XGBoost Regressor

```
±10% return maps to ±1.0
Returns beyond ±10% are clamped to ±1.0
```

BTC regularly makes 5–15% moves in single 4h candles during high volatility. When many predictions are clamped to ±1.0, the regressor ensemble loses resolution — a +10% prediction and a +15% prediction produce identical normalized outputs (+1.0), artificially inflating strong-signal frequency and reducing the discriminative power of the consensus.

**Fix**: Use a percentile-based or volatility-adjusted normalization cap (e.g., ±3× recent ATR expressed as a return), or use a tanh normalization that asymptotically approaches ±1.0 without hard clamping: `tanh(return / scaling_factor)`.

---

## 9 🟡 Signal Threshold (>0.3 = BUY) Contradicts the 60% Consensus Requirement

**Location**: `04-features.md` / `05-logic-reasoning.md` (60% requirement) vs `Paper_Trading…txt` Section 2.2

The technical report maps consensus to decisions:
- `consensus > 0.3` → BUY  
- `consensus < -0.3` → SELL

The features and reasoning documentation both state: *"Requires 60% weighted consensus for execution"* / *"Check signal strength threshold (≥60% consensus)"*.

A consensus value of 0.3 represents 30% net bullish weighting — far below the stated 60% threshold. These thresholds are inconsistent. The system will fire trades at much lower consensus strength than documented, leading to more frequent (and less reliable) signals than intended.

**Fix**: Reconcile the thresholds. If BUY requires 60% consensus, the threshold in the decision synthesis should be 0.6, not 0.3. Update all documentation and the reasoning engine code to use one consistent value.

---

## 10 🟡 Confidence Calibration Formula Is Statistically Unsound

**Location**: `05-logic-reasoning.md` – Step 6

```python
calibrated_confidence = (raw_confidence + historical_accuracy) / 2
```

This simple average overclaims relative to the historical record. Example:
- raw_confidence = 0.90, historical_accuracy = 0.50  
- calibrated_confidence = **0.70** — still claiming 70% success when the historical record at that confidence level is 50%.

Proper calibration (Platt scaling or isotonic regression) would map raw_confidence directly toward the historical accuracy value. The simple average only half-corrects the overconfidence, meaning the agent will systematically overstate its probability of success.

**Fix**: Use `calibrated_confidence = historical_accuracy` when sufficient data is available (e.g., n > 20 in the bucket), blending toward raw_confidence only when data is sparse: `calibrated = w * historical_accuracy + (1 - w) * raw_confidence` where `w = min(1.0, n / 50)`.

---

## 11 🟡 Paper Trading Slippage Applies a Fixed 50% Multiplier

**Location**: `Paper_Trading…txt` Section 1.3

```python
slippage = base_price * (max_slippage_percent/100) * (±0.5) for buy/sell
```

The `±0.5` appears to be a constant directional multiplier rather than a random draw. This means:
- Every buy fill is exactly `base_price × (max_slippage% / 100) × 0.5` above market.
- Every sell fill is exactly the same below market.
- Slippage is always exactly 50% of configured max — never more, never less.

Real slippage is stochastic and should vary per fill to produce realistic P&L distributions.

**Fix**: Replace the fixed multiplier with a random draw: `random.uniform(0, max_slippage_percent/100)` for the magnitude, with direction tied to trade side (positive for buys, negative for sells).

---

## 12 🟡 Learning Disabled → Step 6 Always Applies Flat 20% Confidence Penalty

**Location**: `04-features.md`, `05-logic-reasoning.md` – Step 6

When no historical calibration data exists (learning disabled), the fallback is:
```python
calibrated_confidence = raw_confidence * 0.8
```

With learning permanently disabled (documented as intentional for the lightweight build), the agent **always** applies an unconditional 20% penalty to every confidence value, regardless of how accurate or inaccurate the models actually are. Over time, this makes high-quality signals appear weak and risks suppressing legitimate trades below the confidence threshold.

Additionally, the vector memory (Step 2) continues accumulating context entries but never updates their outcomes — making the historical win-rate data retrieved in Step 2 increasingly stale and unreliable.

**Fix**: Either re-enable learning with a lightweight trade-outcome callback (no ML retraining required), or replace the fallback with a neutral multiplier of 1.0 (no adjustment) until enough data is collected.

---

## 13 🟡 Performance Tracker Uses Wrong Error Metric for Classifiers

**Location**: `03-ml-models.md` – `ModelPerformanceTracker`

```python
error = abs(prediction.prediction - actual_outcome)
```

For classifier models, `prediction.prediction` is a normalized signal in [-1, 1], while `actual_outcome` should be a binary win/loss or directional outcome. Applying absolute error (MAE) across this mix:

- A correct STRONG_BUY (+0.9) on a 0.5% up-move gets error = |0.9 - 0.005| ≈ 0.895 (poor score despite being right).
- A wrong SELL (-0.3) on an up-move gets error = |-0.3 - 0.005| ≈ 0.305 (better score despite being wrong).

This will corrupt model performance weights when the learning module is re-enabled.

**Fix**: Use directional accuracy (sign(prediction) == sign(actual_return)) for all models, or define a separate error function per model type (MAE for regressors, accuracy/AUC for classifiers).

---

## 14 🟡 Close + Reopen Uses Single Ticker Snapshot — Double Slippage Not Simulated

**Location**: `Paper_Trading…txt` Section 1.3 / 4.1

When a signal reversal triggers close-then-open:
> "execute_trade first closes the current position then opens the new one"

Both operations call `_get_fill_price_paper(symbol)` → `get_ticker(symbol)` in sequence. If both use the same cached ticker value (within a single event loop iteration), the close-exit price and the new entry price will be identical (with only the slippage direction flipping). In practice, a simultaneous close and open incurs two separate market-impact slippage events. The current implementation may simulate only one or even net them to zero if buy and sell slippage cancel.

**Fix**: Introduce a small random spread between the close and open fill prices, or explicitly call `get_ticker()` twice with any interim cache-busting, and apply independent random slippage draws to each.

---

## 15 🔵 Training Script Saves Models Without Classifier/Regressor Suffix

**Location**: `03-ml-models.md` – Model Training section

The training script documentation states models are saved as:
- `xgboost_BTCUSD_15m.pkl`

But the "Currently Integrated Models" section expects:
- `xgboost_classifier_BTCUSD_15m.pkl`
- `xgboost_regressor_BTCUSD_15m.pkl`

Model discovery uses the filename suffix to detect model type (`_classifier` / `_regressor`). Models saved without the suffix will either be unregistered or mis-detected as the wrong type, silently breaking regressor normalization (which requires knowing the model type to apply the return-conversion logic).

**Fix**: Update `scripts/train_models.py` to include the model type in the filename, matching the discovery system's naming convention.

---

## Priority Remediation Order

1. **Issue #3** — Fix the 49 vs 50 feature count and retrain models if needed (data integrity).
2. **Issue #1** — Fix classifier normalization to use `P(BUY) - P(SELL)` (prevents garbage signals).
3. **Issue #2** — Decouple exit signals from entry gate filters (prevents missed stop-losses).
4. **Issue #6** — Consolidate to one exit path (prevents double-close race conditions).
5. **Issue #9** — Reconcile consensus threshold (0.3 vs 0.6) in the decision engine.
6. **Issues #4, #5** — Fix agreement score formula and HOLD confidence calculation.
7. **Remaining issues** — Address in order of severity per sprint capacity.
