# JackSparrow Trading Agent — Production-Ready ML Redesign (Reworked)

## Scope
This document is a corrected and production-safe redesign of the ML trading system based on full audit of:
- Training scripts
- Feature pipeline
- Agent inference flow
- Notebook structure

---

# 1. FINAL DIAGNOSIS

## 1.1 HOLD Signal Root Cause (Confirmed)
HOLD dominance is caused by:
- Label imbalance (HOLD majority class)
- Weak feature representation
- Conservative thresholding
- Confidence miscalculation

---

# 2. CRITICAL FIXES (MANDATORY)

## 2.1 REMOVE INCORRECT SELL LOGIC

### ❌ WRONG
SL hit (long) = SELL

### ✅ CORRECT
Train TWO models:

- Long model → TP hit
- Short model → TP hit

---

## 2.2 REMOVE HOLD FROM TRAINING

Use binary classification:

- Long: TP vs NOT TP
- Short: TP vs NOT TP

---

## 2.3 FIX FEATURE PIPELINE (MOST CRITICAL)

### CURRENT (BROKEN)
- Training: feature_pipeline.py
- Live: feature_engineering.py

### FIX
Create ONE unified feature function used by BOTH.

---

## 2.4 FIX CONFIDENCE CALCULATION

### ❌ CURRENT
confidence = HOLD probability

### ✅ FIX
confidence = max(buy_prob, sell_prob)

---

## 2.5 REMOVE CONSENSUS LAYER (TEMPORARY)

Since using only XGBoost:
- Remove ensemble consensus logic
- Use direct model output

---

# 3. FEATURE VALIDATION

## 3.1 EXISTING FEATURES (USED)
- EMA
- RSI
- MACD
- ATR
- ADX
- Bollinger Bands

## 3.2 EXISTING BUT UNUSED FEATURES
- Candlestick patterns (cdl_*)
- Support/Resistance (sr_*)
- Breakout (bo_*)
- Chart patterns (chp_*)

### ISSUE
Agent only uses features defined in metadata → unused features ignored

---

## 3.3 REQUIRED FIX
Retrain model with:
- Candle features
- SR features
- Volatility regime

Then update metadata

---

# 4. TRAINING SCRIPT ISSUES

## 4.1 Identified Problems
- HOLD-heavy labeling
- Sequential feature computation (slow)
- No feature selection
- Misaligned with agent

## 4.2 REQUIRED FIXES
- Replace labeling with TP/SL outcome
- Add feature selection
- Ensure metadata matches features
- Use binary classification

---

# 5. NOTEBOOK STRUCTURE ISSUES

## CURRENT
- Notebook trains model independently
- Scripts exist but not integrated

## FIX
Notebook should:
- Upload scripts
- Run scripts
- NOT duplicate logic

---

# 6. SCALPING CONFIGURATION (CORRECTED)

| Parameter | Value |
|----------|------|
| TP | 0.25–0.35% |
| SL | 0.15–0.25% |
| Timeframe | 5m |
| Lookahead | 4–6 candles |

---

# 7. FINAL PIPELINE (SIMPLIFIED)

Data → Features → XGBoost → Signal → Trade

---

# 8. VALIDATION REQUIREMENTS

Before deployment:

- Feature parity test (training vs live)
- Backtesting (walk-forward)
- Minimum 5 trades/hour in paper trading
- Positive net profit after fees

---

# 9. FINAL CONCLUSION

The system was NOT broken — it was:

- Mis-trained
- Over-filtered
- Under-utilizing features

After fixes:
- HOLD issue will reduce
- Trade frequency will increase
- Scalping becomes feasible

---

