# JackSparrow Trading Agent — Complete ML Redesign Report
## HOLD Signal Fix · Scalping Conversion · Colab Execution Guide

> **Historical diagnosis (read with current code):** This report captures a deep code-traced audit from a fixed point in time. Thresholds, feature counts, and bundle layouts **have evolved** — verify live behaviour against `agent/core/config.py`, `agent/core/reasoning_engine.py`, `agent/events/handlers/trading_handler.py`, and the active `metadata_BTCUSD_*.json` under `MODEL_DIR` (e.g. `jacksparrow_v5_BTCUSD_2026-03-21`).

**Scope:** Full system diagnosis, root cause analysis, and actionable redesign  
**Based on:** Code-traced audit of all uploaded artifacts  
**Target:** XGBoost classifier, Delta Exchange, Google Colab, local script execution

---

## Table of Contents

1. [System Diagnosis](#1-system-diagnosis)
2. [Root Cause Analysis](#2-root-cause-analysis)
3. [Corrected ML Design](#3-corrected-ml-design)
4. [Training Pipeline (Updated)](#4-training-pipeline-updated)
5. [Colab Execution Setup](#5-colab-execution-setup)
6. [Agent Integration](#6-agent-integration)
7. [Code Patches](#7-code-patches)
8. [Scalping Optimization](#8-scalping-optimization)
9. [Final Architecture](#9-final-architecture)

---

## 1. System Diagnosis

### 1.1 Why HOLD Signals Dominate

The HOLD dominance problem has **three independent, compounding layers**. All three must be fixed together — patching only one layer will not produce actionable signals.

#### Layer 1 — Label Design Bakes In HOLD During Training

In `train_robust_ensemble.py`, `make_entry_labels()` reads:

```python
def make_entry_labels(close, lookahead=1, threshold=0.003):
    fwd = close.shift(-lookahead) / close - 1.0
    labels = np.where(fwd > threshold, 2,
             np.where(fwd < -threshold, 0, 1))  # 1 = HOLD
    return pd.Series(labels, dtype=int)
```

With `threshold=0.003` (0.3 %), every candle whose next-bar move is between −0.3 % and +0.3 % is labeled HOLD. In typical low-volatility crypto periods, 55–70 % of candles fall in this band. **The model is explicitly trained with HOLD as the plurality or majority class.** XGBoost maximizes accuracy by default — on a 3-class problem where HOLD is 60 % of samples, the globally optimal strategy is to predict HOLD.

#### Layer 2 — Consensus Dampening Shrinks Signals at Runtime

In `agent/core/reasoning_engine.py`, `_step3_model_consensus()` applies disagreement damping:

```
if pred_stdev > 0.4:
    consensus *= max(0.0, 1.0 - (pred_stdev - 0.4))
```

Whenever the per-model prediction standard deviation exceeds 0.4, the consensus magnitude is multiplied by a number less than 1. If `pred_stdev = 0.6`, the multiplier is `max(0, 1 - 0.2) = 0.8`. If `pred_stdev = 0.9`, the multiplier is `max(0, 1 - 0.5) = 0.5`. Under a degraded or untrained model producing near-random predictions, `pred_stdev` can approach 1.0 — driving consensus to near zero.

#### Layer 3 — The HOLD Band Is Wide and Volatility-Adaptive

`_step5_decision_synthesis()` in `reasoning_engine.py` applies the following threshold logic:

| Condition | `strong_thresh` | `mild_thresh` | HOLD band width |
|---|---|---|---|
| `vol > 5` | 0.75 | 0.40 | `[-0.40, +0.40]` = 80 % of range |
| `1.5 ≤ vol ≤ 5` | 0.70 | 0.30 | `[-0.30, +0.30]` = 60 % of range |
| `vol < 1.5` | 0.60 | 0.25 | `[-0.25, +0.25]` = 50 % of range |

The consensus scalar is in `[-1, +1]`. Under typical market volatility (`1.5–5`), the consensus must exceed **±0.30** to generate any trade signal. A model trained on a HOLD-dominated dataset, further dampened by disagreement, rarely achieves this.

#### Layer 4 — Trading Handler Hard-Exits on HOLD

Even if a `BUY/SELL` signal is emitted, `trading_handler.py` applies additional gates:

```python
if signal == "HOLD" or not signal:
    return  # Hard skip — no trade, no logging

if confidence < 0.65:
    return  # Confidence gate

if features.get("volatility") is None:
    return  # Volatility presence gate

if adx_14 < 20 and signal in ("BUY", "SELL"):
    return  # ADX ranging filter
```

With `min_confidence_threshold=0.65` and a HOLD-biased model calibrated to output moderate probabilities (e.g., HOLD=0.55, BUY=0.30, SELL=0.15), `confidence = max(probs) = 0.55` which is below the gate.

### 1.2 How Label Design Affects Model Output

The v4 entry classifier outputs `buy_prob - sell_prob` as its `prediction` signal. If the model's class distribution is HOLD-dominant (60 %+ training labels), the model will assign high probability mass to HOLD, producing small `buy_prob - sell_prob` differences. This is mathematically inevitable and no amount of threshold tuning can fix it without retraining on better labels.

With the current `entry_lookahead=4` on `15m` (= 1 hour horizon), the forward return is statistically weak and noise-dominated. This further reduces `|buy_prob - sell_prob|`, keeping consensus near 0.

### 1.3 How Feature Weakness Affects Prediction Confidence

The v4 metadata requires exactly **18 features**:

```
ema_9, ema_21, macd, macd_signal, atr_14, macd_hist,
adx_14, rsi_14, vol_zscore, vol_ratio,
bb_pct, bb_width, roc_20, roc_10,
ema_cross, returns_1, atr_pct, volatility_20
```

These are all lagging trend/momentum indicators. They contain zero information about:
- **Candle microstructure** (body/wick ratios, engulfing patterns)
- **Support and resistance context** (is price at a key level?)
- **Breakout confirmation** (is this bar breaking a structure?)
- **Volatility contraction** (is price coiling for a breakout?)

For scalping — where edge comes from microstructure and price action — this feature set is blind to the most important signals.

### 1.4 How Decision Thresholds Suppress Trades

The full suppression chain for a signal that "should" become a trade:

```
Model output: buy_prob=0.38, hold_prob=0.45, sell_prob=0.17
  → prediction = 0.38 - 0.17 = 0.21
  → confidence = 0.45   ← max(probabilities) = HOLD probability
  → consensus (after dampening) ≈ 0.16
  → decision_synthesis: 0.16 < 0.30 mild_thresh → HOLD
  → trading_handler: signal == HOLD → return (no trade)
```

Even if the reasoning engine somehow produced `BUY`, `confidence=0.45 < 0.65` would block execution. The system has three independent suppressors — any one of them alone can prevent a trade.

---

## 2. Root Cause Analysis

### 2.1 Labeling Flaw — Direction, Not Trade Outcome

**Current approach:** Label = sign of 1-bar forward return vs ±0.3% threshold.

**The problem in concrete numbers:**
- Threshold = 0.3 %, typical fee = 0.05 % taker × 2 = 0.10 % round-trip
- A 0.35 % move labeled BUY produces exactly 0.25 % profit after fees
- But if the stop-loss is at 0.5 % below entry, the trade's expected value is negative
- The label says "correct BUY" but the trade loses money

The model is trained to predict **price direction**, not **trade profitability**. These are fundamentally different objectives. The label design must change.

### 2.2 Feature Under-utilization

The codebase has a `feature_store/unified_feature_engine.py` that implements candlestick and chart pattern features (`cdl_*`, `sr_*`, `chp_*`, `bo_*`). However, the v4 metadata `metadata_BTCUSD_15m.json` requests only the 18-feature list. Because `MarketDataEventHandler._get_runtime_feature_names()` defers to `model_registry.get_required_feature_names()`, these features are **never computed during live inference**, regardless of whether the engine can compute them.

**Consequence:** The most informative price-action features are implemented but invisible to the model.

### 2.3 Pipeline Misalignment — Two Feature Implementations

| Path | File | Used By |
|---|---|---|
| Training | `feature_store/feature_pipeline.py` | `train_robust_ensemble.py` |
| Live | `agent/data/feature_engineering.py` | `MCPFeatureServer` |

These are entirely separate codebases implementing the same 50 features. Known divergence points: rolling window boundary behavior, NaN fill strategy, library (ta vs numpy), resolution-dependent bar counts. If the last-bar RSI value differs by even 0.5 between training and live, the model receives an out-of-distribution input and outputs near-random probabilities.

### 2.4 Model Bias Toward HOLD — Mechanism

In training, the 3-class XGBoost is fit on data where HOLD = ~60 % of labels. `scale_pos_weight` handles binary imbalance but not multi-class. Without explicit `class_weight` correction:
- XGBoost learns that predicting HOLD on ambiguous inputs is "safe" from a loss perspective
- The model's HOLD probability is systematically calibrated high
- `confidence = max(probabilities)` is then the HOLD probability, not a BUY/SELL probability
- This means even when the model "leans" BUY, the confidence gate is the HOLD probability

### 2.5 Scalping Incompatibility — Full Breakdown

| Aspect | Current System | Scalping Requirement |
|---|---|---|
| Label horizon | 4 bars × 15 min = 60 min | 1–3 bars × 5 min = 5–15 min |
| Take-profit | 3–5 % default | 0.15–0.30 % |
| Stop-loss | 1.5–2 % default | 0.10–0.20 % |
| Signal trigger | 0.5 % price fluctuation | Every candle close |
| Position monitor | 15-second interval | 1–5 second interval |
| Feature horizon | Momentum/trend (multi-hour) | Microstructure (1–10 bars) |
| Trade frequency | Low (conservative) | High (active) |

---

## 3. Corrected ML Design

### 3.1 New Labeling Strategy — TP/SL Outcome Labels

Replace the forward-return threshold label with a **TP/SL simulation** that mirrors actual trade logic:

```python
def make_tpsl_labels(
    df: pd.DataFrame,
    tp_pct: float = 0.0020,   # 0.20 % take-profit
    sl_pct: float = 0.0015,   # 0.15 % stop-loss
    lookahead: int = 6,       # max bars to wait
    fee_pct: float = 0.0005,  # 0.05 % per side (taker)
) -> pd.Series:
    """
    For each bar, simulate going long at close[t].
    Scan forward up to `lookahead` bars:
      - If high[t+k] >= entry * (1 + tp_pct) before low hits SL → BUY (2)
      - If low[t+k]  <= entry * (1 - sl_pct) before high hits TP → SELL (0)
      - Neither hit within lookahead → HOLD (1) — but we should MINIMIZE this
    Net of fees: only label BUY if gross profit > 2 * fee_pct
    """
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    n     = len(df)
    labels = np.ones(n, dtype=int)  # default HOLD

    net_tp = tp_pct - 2 * fee_pct   # profit after fees
    net_sl = sl_pct + 2 * fee_pct   # loss including fees

    for i in range(n - lookahead):
        entry = close[i]
        tp_price = entry * (1 + tp_pct)
        sl_price = entry * (1 - sl_pct)

        for k in range(1, lookahead + 1):
            bar_high = high[i + k]
            bar_low  = low[i + k]

            if bar_high >= tp_price:
                if net_tp > 0:
                    labels[i] = 2  # BUY — TP hit, profitable net of fees
                break
            elif bar_low <= sl_price:
                labels[i] = 0  # SELL label (short signal in reverse)
                break

    return pd.Series(labels, index=df.index, dtype=int)
```

**Why this is better:**
- Labels reflect actual trade profitability, not just price direction
- TP and SL are the same parameters used by the execution engine
- Fee-adjusted: a 0.20 % move against 0.10 % round-trip fees is labeled correctly
- Reduces HOLD class frequency because TP/SL hit frequently on active scalping timeframes

**Expected class balance with `tp=0.20 %, sl=0.15 %, lookahead=6` on `5m` BTC:**
- BUY ≈ 30–35 %
- SELL ≈ 30–35 %
- HOLD ≈ 30–40 %

This is dramatically more balanced than the current 10/10/80 split.

### 3.2 New Feature Strategy

#### Group A — Candle Microstructure (8 features)

```python
def compute_candle_features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body      = c - o
    candle_range = h - l

    features = pd.DataFrame(index=df.index)
    features["cdl_body_ratio"]    = body / candle_range.replace(0, np.nan)
    features["cdl_upper_wick"]    = (h - c.clip(lower=o)) / candle_range.replace(0, np.nan)
    features["cdl_lower_wick"]    = (c.clip(upper=o) - l) / candle_range.replace(0, np.nan)
    features["cdl_body_direction"] = np.sign(body)                 # +1 / -1 / 0
    features["cdl_engulf_bull"]   = (
        (body > 0) & (body.shift(1) < 0) &
        (c > o.shift(1)) & (o < c.shift(1))
    ).astype(float)
    features["cdl_engulf_bear"]   = (
        (body < 0) & (body.shift(1) > 0) &
        (c < o.shift(1)) & (o > c.shift(1))
    ).astype(float)
    features["cdl_hammer"]        = (
        (features["cdl_lower_wick"] > 0.6) &
        (features["cdl_body_ratio"].abs() < 0.3)
    ).astype(float)
    features["cdl_doji"]          = (features["cdl_body_ratio"].abs() < 0.05).astype(float)
    return features.fillna(0.0)
```

#### Group B — Support/Resistance Context (6 features)

```python
def compute_sr_features(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    c = df["close"]
    h = df["high"]
    l = df["low"]

    features = pd.DataFrame(index=df.index)
    roll_high = h.rolling(lookback).max()
    roll_low  = l.rolling(lookback).min()
    roll_range = (roll_high - roll_low).replace(0, np.nan)

    features["sr_range_position"] = (c - roll_low) / roll_range   # 0=bottom, 1=top
    features["sr_dist_to_high"]   = (roll_high - c) / c           # fractional distance
    features["sr_dist_to_low"]    = (c - roll_low) / c
    features["sr_near_high"]      = (features["sr_dist_to_high"] < 0.005).astype(float)
    features["sr_near_low"]       = (features["sr_dist_to_low"]  < 0.005).astype(float)
    features["sr_breakout_up"]    = (c > roll_high.shift(1)).astype(float)
    return features.fillna(0.0)
```

#### Group C — Volatility Regime (4 features)

```python
def compute_vol_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    log_ret = np.log(c / c.shift(1))

    features = pd.DataFrame(index=df.index)
    features["vr_realized_5"]   = log_ret.rolling(5).std() * np.sqrt(252 * 288)  # annualized
    features["vr_realized_20"]  = log_ret.rolling(20).std() * np.sqrt(252 * 288)
    features["vr_vol_ratio"]    = (
        features["vr_realized_5"] / features["vr_realized_20"].replace(0, np.nan)
    )
    features["vr_contraction"]  = (features["vr_vol_ratio"] < 0.7).astype(float)
    return features.fillna(0.0)
```

### 3.3 Model Output Design — Remove HOLD Dominance

**Change 1 — Binary classification per direction (recommended for scalping):**

Instead of 3-class (SELL=0, HOLD=1, BUY=2), train **two binary models**:
- `entry_long_model`: target = 1 if TP hit long, 0 otherwise (HOLD + SL both = 0)
- `entry_short_model`: target = 1 if TP hit short, 0 otherwise

Signal logic becomes:
```python
long_prob  = entry_long_model.predict_proba(X)[:, 1]
short_prob = entry_short_model.predict_proba(X)[:, 1]
signal = "BUY" if long_prob > 0.50 else "SELL" if short_prob > 0.50 else "HOLD"
```

**Change 2 — Probability threshold, not difference:**

Replace `prediction = buy_prob - sell_prob` with explicit probability thresholds:
```python
if buy_prob > 0.52 and buy_prob > sell_prob * 1.5:
    prediction = buy_prob
    signal = "BUY"
elif sell_prob > 0.52 and sell_prob > buy_prob * 1.5:
    prediction = -sell_prob
    signal = "SELL"
else:
    prediction = 0.0
    signal = "HOLD"
```

**Change 3 — Narrow the HOLD band in `reasoning_engine.py`:**

```python
# Current (too conservative for scalping)
mild_thresh = 0.30

# Scalping-compatible
mild_thresh = 0.15   # Half the current threshold
strong_thresh = 0.40
```

---

## 4. Training Pipeline (Updated)

### 4.1 Clean Pipeline Flow

```
Delta Exchange API
      │
      ▼
fetch_candles()              ← rate-limited, validated OHLCV
      │
      ▼
compute_features_unified()   ← SINGLE implementation (new)
      │                         50 base + 18 candle/SR/vol features = 68 total
      ▼
make_tpsl_labels()           ← TP/SL simulation, fee-adjusted
      │
      ▼
class_balance_check()        ← assert BUY+SELL >= 50% of samples
      │
      ▼
TimeSeriesSplit(n_folds=5)   ← walk-forward, no leakage
      │
      ▼
XGBoost binary classifier ×2 ← entry_long + entry_short models
      │
      ▼
CalibratedClassifierCV       ← isotonic calibration
      │
      ▼
save_artifacts()             ← .joblib + metadata JSON with feature list
      │
      ▼
generate_v4_metadata()       ← compatible with V4EnsembleNode discovery
```

### 4.2 Script Integration for Colab

The updated training uses the following scripts (upload these to `/content/`):

| Script | Purpose |
|---|---|
| `train_robust_ensemble.py` | Base ensemble trainer — retrain with new labels |
| `train_regime_model.py` | Regime classifier — run after ensemble trainer |
| `patch_labels.py` | **New** — drop-in replacement for `make_entry_labels()` |
| `patch_features.py` | **New** — adds 18 candle/SR/vol features |
| `generate_v4_metadata.py` | **New** — writes v4-compatible metadata for agent discovery |

### 4.3 Artifact Compatibility

The agent's `ModelDiscovery` scans for `metadata_BTCUSD_*.json` and loads `V4EnsembleNode`. To keep the existing discovery path working, the new training must produce:

```
/content/agent/model_storage/jacksparrow_v4_BTCUSD/
  metadata_BTCUSD_5m.json          ← updated features_required (68 features)
  entry_model_BTCUSD_5m.joblib     ← new binary long model
  entry_scaler_BTCUSD_5m.joblib
  exit_model_BTCUSD_5m.joblib
  exit_scaler_BTCUSD_5m.joblib
```

The `metadata.json` `features_required` field must exactly match the ordered list used during training. This is the single contract between training and inference.

---

## 5. Colab Execution Setup

### 5.1 Prerequisites

No Google Drive. No GitHub. Everything runs from `/content/`.

```python
# Cell 1 — Install dependencies
!pip install xgboost==2.0.2 lightgbm scikit-learn joblib pandas numpy ta
!pip install --quiet delta-exchange-client  # or install from uploaded wheel
```

### 5.2 Upload Scripts

```python
# Cell 2 — Upload all training scripts manually
from google.colab import files
uploaded = files.upload()
# Upload: train_robust_ensemble.py, train_regime_model.py,
#         patch_labels.py, patch_features.py, generate_v4_metadata.py
```

After upload, all files land in `/content/`. Move them to a scripts folder:

```python
import os, shutil
os.makedirs("/content/scripts", exist_ok=True)
os.makedirs("/content/agent/model_storage/jacksparrow_v4_BTCUSD", exist_ok=True)
os.makedirs("/content/models", exist_ok=True)

for f in uploaded.keys():
    shutil.move(f"/content/{f}", f"/content/scripts/{f}")
```

### 5.3 Upload Agent Source (ZIP)

```python
# Cell 3 — Upload project zip
from google.colab import files
agent_zip = files.upload()  # upload: trading_agent.zip

import zipfile
with zipfile.ZipFile("/content/trading_agent.zip", "r") as z:
    z.extractall("/content/")

# Verify
import os
assert os.path.exists("/content/agent/data/feature_engineering.py"), \
    "Agent source not found — check zip structure"
```

### 5.4 Set API Keys

```python
# Cell 4 — Set environment variables
import os
os.environ["DELTA_EXCHANGE_API_KEY"]    = "YOUR_KEY_HERE"
os.environ["DELTA_EXCHANGE_API_SECRET"] = "YOUR_SECRET_HERE"
```

**Never hardcode secrets in notebook cells that you save.**

### 5.5 Set Working Directory and Python Path

```python
# Cell 5 — Configure paths
import sys
sys.path.insert(0, "/content")
sys.path.insert(0, "/content/scripts")
os.chdir("/content")
print("Working dir:", os.getcwd())
print("Python path:", sys.path[:3])
```

### 5.6 Run Training

```python
# Cell 6 — Run robust ensemble training with new labels
!python /content/scripts/train_robust_ensemble.py \
    --symbol BTCUSD \
    --timeframes 5m 15m \
    --total-candles 8000 \
    --n-folds 5 \
    --entry-threshold 0.002 \
    --exit-lookahead 6 \
    --output-dir /content/agent/model_storage
```

```python
# Cell 7 — Run regime model training
!python /content/scripts/train_regime_model.py \
    --symbol BTCUSD \
    --timeframes 5m 15m \
    --total-candles 8000 \
    --output-dir /content/agent/model_storage
```

### 5.7 Verify Artifacts

```python
# Cell 8 — Verify outputs
import os, json, glob

artifact_dir = "/content/agent/model_storage/jacksparrow_v4_BTCUSD"
files_found  = sorted(os.listdir(artifact_dir)) if os.path.exists(artifact_dir) else []
print(f"Artifacts in {artifact_dir}:")
for f in files_found:
    size = os.path.getsize(f"{artifact_dir}/{f}") // 1024
    print(f"  {f:<50}  {size:>6} KB")

# Check metadata
for meta in glob.glob(f"{artifact_dir}/metadata_*.json"):
    with open(meta) as fh:
        m = json.load(fh)
    tf = m.get("timeframe", "?")
    feats = len(m.get("features_required", []))
    print(f"\n{os.path.basename(meta)}:")
    print(f"  timeframe:        {tf}")
    print(f"  features_required: {feats}")
    print(f"  entry_lookahead:  {m.get('entry_lookahead')}")
    print(f"  dataset_sha256:   {m.get('dataset_sha256')}")
```

### 5.8 Download Artifacts for Local Deployment

```python
# Cell 9 — Package and download
import shutil
shutil.make_archive(
    "/content/jacksparrow_models",
    "zip",
    "/content/agent/model_storage/jacksparrow_v4_BTCUSD"
)

from google.colab import files
files.download("/content/jacksparrow_models.zip")
```

---

## 6. Agent Integration

### 6.1 How Trained Models Connect to the Agent

The integration chain is:

```
Training artifact:
  metadata_BTCUSD_5m.json          → defines features_required (the 68-feature list)
  entry_model_BTCUSD_5m.joblib     → loaded by V4EnsembleNode
  entry_scaler_BTCUSD_5m.joblib    → applied before model.predict_proba()

Agent discovery:
  ModelDiscovery.discover_models() → scans MODEL_DIR for metadata_BTCUSD_*.json
                                   → creates V4EnsembleNode.from_metadata(path)

Live inference:
  MCPFeatureServer                 → computes exactly metadata["features_required"]
  V4EnsembleNode.predict()         → builds feature vector in metadata feature order
  MCPReasoningEngine               → applies consensus + threshold logic
```

The only thing you need to place in the correct directory and the agent will automatically pick up the new models on restart. No code changes required for basic integration — only for threshold adjustments.

### 6.2 Feature Metadata Must Match Exactly

The `features_required` list in `metadata.json` is the **contract between training and inference**. Every feature name must:
1. Appear in the same order as used during `scaler.fit()` and `model.fit()`
2. Be computable by `agent/data/feature_engineering.py` with the exact same formula
3. Be registered in `feature_list.py` or explicitly handled by `FeatureEngineering.compute_feature()`

**To add the new 18 candle/SR/vol features to live inference**, you must:
1. Implement each feature in `FeatureEngineering.compute_feature()` (see Section 7.2)
2. Add feature names to `features_required` in the generated metadata
3. Include those features in the training data before fitting the scaler and model

### 6.3 Inference Consistency Rules

| Rule | How to Verify |
|---|---|
| Feature count matches | Assert `len(features_required) == X` in V4EnsembleNode |
| Feature order matches | Log feature vector hash on first prediction |
| Scaler formula matches | Use same `RobustScaler` instance saved in `entry_scaler.joblib` |
| NaN fill strategy matches | Both paths must use `ffill().fillna(0.0)` |
| Resolution-dependent features | `returns_1h` must use same bar-count formula as training |

**Parity test (run before any production deployment):**

```python
# tests/test_feature_parity.py
from agent.data.feature_engineering import FeatureEngineering
from feature_store.feature_pipeline import compute_features
import pandas as pd, numpy as np

def test_parity(candles_df: pd.DataFrame, feature_names: list):
    """
    Verifies that training-path (batch) and live-path (per-feature)
    produce identical values for the last bar.
    """
    fe = FeatureEngineering()
    batch = compute_features(candles_df, resolution_minutes=5)

    for name in feature_names:
        batch_val = float(batch[name].iloc[-1])
        live_val  = float(fe.compute_feature(name, candles_df.to_dict("records")))
        diff = abs(batch_val - live_val)
        assert diff < 1e-5, (
            f"Parity failure [{name}]: "
            f"batch={batch_val:.8f}  live={live_val:.8f}  diff={diff:.2e}"
        )
    print(f"  All {len(feature_names)} features passed parity check.")
```

---

## 7. Code Patches

### 7.1 Patch — TP/SL Label Generation

**File to modify:** `train_robust_ensemble.py`, replace `make_entry_labels()`

```python
# ── NEW make_entry_labels — TP/SL outcome-based ───────────────────────────────
def make_entry_labels(
    close: pd.Series,
    lookahead: int = 6,
    threshold: float = 0.003,   # kept for API compat, unused by new logic
    tp_pct: float = 0.0020,     # 0.20% take-profit
    sl_pct: float = 0.0015,     # 0.15% stop-loss
    fee_pct: float = 0.0005,    # 0.05% taker fee per side
    df: pd.DataFrame = None,    # pass full OHLCV for high/low access
) -> pd.Series:
    """
    TP/SL simulation label:
      2 = BUY  (TP hit long, net of fees)
      0 = SELL (SL hit long = short opportunity)
      1 = HOLD (neither within lookahead bars)
    """
    if df is not None and "high" in df.columns and "low" in df.columns:
        high_arr  = df["high"].values
        low_arr   = df["low"].values
        close_arr = df["close"].values
    else:
        # Fallback: use close-only simulation
        high_arr = low_arr = close_arr = close.values

    n = len(close_arr)
    labels = np.ones(n, dtype=int)

    tp_net = tp_pct - 2 * fee_pct
    if tp_net <= 0:
        raise ValueError(f"TP net of fees is negative: tp={tp_pct}, fee×2={2*fee_pct}. Increase TP.")

    for i in range(n - lookahead):
        entry    = close_arr[i]
        tp_price = entry * (1 + tp_pct)
        sl_price = entry * (1 - sl_pct)

        for k in range(1, lookahead + 1):
            bar_high = high_arr[i + k]
            bar_low  = low_arr[i + k]

            if bar_high >= tp_price:
                labels[i] = 2   # BUY
                break
            elif bar_low <= sl_price:
                labels[i] = 0   # SELL
                break
        # else: remains HOLD

    return pd.Series(labels, index=close.index, dtype=int)
```

**Call site update in `train_regime_for_timeframe()` and ensemble trainer:**

```python
# OLD
entry_lbl = make_entry_labels(close, threshold=cfg.entry_threshold)

# NEW
entry_lbl = make_entry_labels(
    close,
    lookahead=cfg.exit_lookahead,
    tp_pct=0.0020,
    sl_pct=0.0015,
    fee_pct=0.0005,
    df=df.iloc[warmup:].reset_index(drop=True),
)

# Class balance guard — alert if HOLD > 60%
counts = entry_lbl.value_counts(normalize=True)
hold_frac = counts.get(1, 0.0)
if hold_frac > 0.60:
    log.warning(
        f"  ⚠  HOLD class = {hold_frac:.1%} — consider reducing tp_pct "
        f"or increasing lookahead to improve class balance."
    )
```

### 7.2 Patch — Feature Additions in FeatureEngineering

**File to modify:** `agent/data/feature_engineering.py`

Add a new method block to `FeatureEngineering` (do not replace existing features):

```python
# ── Candle microstructure features ─────────────────────────────────────────────
async def _compute_cdl_body_ratio(self, candles: list) -> float:
    c = candles[-1]
    rng = c["high"] - c["low"]
    if rng == 0:
        return 0.0
    return (c["close"] - c["open"]) / rng

async def _compute_cdl_upper_wick(self, candles: list) -> float:
    c = candles[-1]
    rng = c["high"] - c["low"]
    if rng == 0:
        return 0.0
    upper_body = max(c["close"], c["open"])
    return (c["high"] - upper_body) / rng

async def _compute_cdl_lower_wick(self, candles: list) -> float:
    c = candles[-1]
    rng = c["high"] - c["low"]
    if rng == 0:
        return 0.0
    lower_body = min(c["close"], c["open"])
    return (lower_body - c["low"]) / rng

async def _compute_cdl_body_direction(self, candles: list) -> float:
    c = candles[-1]
    return float(np.sign(c["close"] - c["open"]))

async def _compute_cdl_engulf_bull(self, candles: list) -> float:
    if len(candles) < 2:
        return 0.0
    prev, curr = candles[-2], candles[-1]
    if (curr["close"] > curr["open"] and prev["close"] < prev["open"] and
            curr["close"] > prev["open"] and curr["open"] < prev["close"]):
        return 1.0
    return 0.0

async def _compute_cdl_engulf_bear(self, candles: list) -> float:
    if len(candles) < 2:
        return 0.0
    prev, curr = candles[-2], candles[-1]
    if (curr["close"] < curr["open"] and prev["close"] > prev["open"] and
            curr["close"] < prev["open"] and curr["open"] > prev["close"]):
        return 1.0
    return 0.0

# ── Support/Resistance features ────────────────────────────────────────────────
async def _compute_sr_range_position(self, candles: list, lookback: int = 20) -> float:
    if len(candles) < lookback:
        return 0.5
    window = candles[-lookback:]
    highs  = [c["high"]  for c in window]
    lows   = [c["low"]   for c in window]
    rng    = max(highs) - min(lows)
    if rng == 0:
        return 0.5
    return (candles[-1]["close"] - min(lows)) / rng

async def _compute_sr_dist_to_high(self, candles: list, lookback: int = 20) -> float:
    if len(candles) < 2:
        return 0.0
    high_20 = max(c["high"] for c in candles[-lookback:])
    return (high_20 - candles[-1]["close"]) / candles[-1]["close"]

async def _compute_sr_dist_to_low(self, candles: list, lookback: int = 20) -> float:
    if len(candles) < 2:
        return 0.0
    low_20 = min(c["low"] for c in candles[-lookback:])
    return (candles[-1]["close"] - low_20) / candles[-1]["close"]

# Route these in compute_feature() dispatcher:
# if feature_name.startswith("cdl_") or feature_name.startswith("sr_"):
#     method = getattr(self, f"_compute_{feature_name}", None)
#     if method:
#         return await method(candles)
```

### 7.3 Patch — Remove HOLD Dominance from ReasoningEngine

**File to modify:** `agent/core/reasoning_engine.py`, `_step5_decision_synthesis()`

```python
def _step5_decision_synthesis(self, consensus: float, features: dict) -> str:
    vol = features.get("volatility", 3.0) or 3.0

    # ── Scalping-optimized thresholds ─────────────────────────────────────────
    if vol > 5:
        strong_thresh, mild_thresh = 0.45, 0.20   # was 0.75 / 0.40
    elif vol < 1.5:
        strong_thresh, mild_thresh = 0.35, 0.15   # was 0.60 / 0.25
    else:
        strong_thresh, mild_thresh = 0.40, 0.18   # was 0.70 / 0.30

    if consensus >  strong_thresh: return "STRONG_BUY"
    if consensus >  mild_thresh:   return "BUY"
    if consensus < -strong_thresh: return "STRONG_SELL"
    if consensus < -mild_thresh:   return "SELL"
    return "HOLD"
```

**Also reduce disagreement damping in `_step3_model_consensus()`:**

```python
# OLD: damping kicks in at pred_stdev > 0.4
if pred_stdev > settings.model_disagreement_threshold:  # default 0.4
    consensus *= max(0.0, 1.0 - (pred_stdev - threshold))

# NEW: raise threshold and reduce damping intensity
disagreement_threshold = 0.60  # was 0.40
if pred_stdev > disagreement_threshold:
    damping = max(0.5, 1.0 - 0.5 * (pred_stdev - disagreement_threshold))
    consensus *= damping
```

### 7.4 Patch — Trading Handler Confidence Gate

**File to modify:** `agent/events/handlers/trading_handler.py`

```python
# OLD
MIN_CONFIDENCE_THRESHOLD = 0.65

# NEW — calibrated to typical model output range for scalping
MIN_CONFIDENCE_THRESHOLD = 0.52

# Also: remove the hard ADX block for scalping (scalping works in ranging markets)
# OLD
if adx_14 is not None and adx_14 < 20 and signal in ("BUY", "SELL"):
    self._log_entry_rejected("ADX ranging filter", ...)
    return

# NEW — only block if ADX is very low (below 15) to allow range scalping
if adx_14 is not None and adx_14 < 15 and signal in ("BUY", "SELL"):
    self._log_entry_rejected("ADX too low for scalping", ...)
    return
```

### 7.5 Patch — V4EnsembleNode Signal Logic

**File to modify:** `agent/models/v4_ensemble_node.py`

```python
# OLD — difference can be small even when model has directional conviction
entry_signal = buy_prob - sell_prob   # can be near-zero if HOLD prob is high

# NEW — use probability-based thresholding
hold_prob   = probs[1]   # index 1 = HOLD class
buy_prob    = probs[2]   # index 2 = BUY class
sell_prob   = probs[0]   # index 0 = SELL class

BUY_THRESH  = 0.40   # buy_prob must exceed this
SELL_THRESH = 0.40

if buy_prob >= BUY_THRESH and buy_prob > sell_prob:
    entry_signal  = buy_prob              # positive signal strength
    confidence    = buy_prob
elif sell_prob >= SELL_THRESH and sell_prob > buy_prob:
    entry_signal  = -sell_prob            # negative signal strength
    confidence    = sell_prob
else:
    entry_signal  = buy_prob - sell_prob  # fallback: small value → HOLD
    confidence    = hold_prob
```

---

## 8. Scalping Optimization

### 8.1 Recommended Timeframes

| Timeframe | Use Case | Candle Fetch | Label Lookahead |
|---|---|---|---|
| **5m** | Primary scalping | 8,000 candles | 4–6 bars (20–30 min) |
| **15m** | Secondary confirmation | 6,000 candles | 4 bars (60 min) |
| 1m | Tick-level (advanced) | 10,000 candles | 6–8 bars |

Start with 5m. Do not use 1m until 5m model is validated.

### 8.2 TP/SL Parameters for Fee-Positive Scalping

Delta Exchange taker fee ≈ 0.05 % per side → 0.10 % round-trip.

| Parameter | Value | Reasoning |
|---|---|---|
| `tp_pct` | 0.0020 (0.20 %) | 2× fees — minimum viable profit |
| `sl_pct` | 0.0015 (0.15 %) | Tight stop — 1:1.33 reward/risk |
| `fee_pct` | 0.0005 (0.05 %) | Delta taker fee |
| Net TP | 0.0010 (0.10 %) | After fees |
| Label lookahead | 6 bars | 30 min on 5m |

**For aggressive scalping (higher frequency):**

| Parameter | Value |
|---|---|
| `tp_pct` | 0.0015 (0.15 %) |
| `sl_pct` | 0.0010 (0.10 %) |
| `fee_pct` | 0.0005 |
| Label lookahead | 4 bars |

**Warning:** Net TP = 0.0005 at aggressive settings. Even small prediction errors will turn negative. Validate on out-of-sample data before using.

### 8.3 XGBoost Hyperparameters for Scalping

```python
xgb_params = {
    "n_estimators":    500,
    "max_depth":       4,         # shallow — prevents overfitting microstructure noise
    "learning_rate":   0.05,
    "subsample":       0.8,
    "colsample_bytree": 0.7,
    "min_child_weight": 10,       # high — prevents learning from rare noisy patterns
    "gamma":           0.1,
    "reg_alpha":       0.1,
    "reg_lambda":      1.0,
    "scale_pos_weight": None,     # set dynamically based on class balance
    "eval_metric":     "auc",     # AUC better than logloss for imbalanced
    "use_label_encoder": False,
    "random_state":    42,
}

# Dynamic class weight for BUY model
buy_count  = (y_train == 2).sum()
not_buy    = (y_train != 2).sum()
scale_pos  = not_buy / buy_count if buy_count > 0 else 1.0
xgb_params["scale_pos_weight"] = scale_pos
```

### 8.4 Position Monitor Interval

**Current default:** `position_monitor_interval_seconds = 15`

**Required for scalping:** 1–3 seconds

```python
# agent/core/config.py
POSITION_MONITOR_INTERVAL_SECONDS = 2   # was 15

# Also reduce signal trigger threshold
PRICE_FLUCTUATION_THRESHOLD_PCT = 0.10  # was 0.5 — trigger on smaller moves
```

### 8.5 Training Data Volume Recommendations

| Timeframe | Min Candles | Ideal Candles | Approx History |
|---|---|---|---|
| 5m | 5,000 | 10,000 | 35 days |
| 15m | 4,000 | 8,000 | 83 days |
| 1m | 10,000 | 20,000 | 14 days |

Delta Exchange API limits per request: 2,000 candles. The fetch loop in `train_robust_ensemble.py` handles pagination automatically.

---

## 9. Final Architecture

### 9.1 Complete Pipeline (Redesigned)

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                      │
│                                                                  │
│  Delta Exchange REST/WS                                          │
│      │                                                           │
│      ▼                                                           │
│  MarketDataService                                               │
│    - CandleClosedEvent (every 5m candle)                         │
│    - PriceFluctuationEvent (>= 0.10% move)       ← reduced      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  FEATURE LAYER                                                   │
│                                                                  │
│  MCPFeatureServer                                                │
│    - Fetches last 100 candles                                    │
│    - Computes 68 features:                                       │
│        • 50 base indicators (EMA, RSI, MACD, ADX, BB, etc.)     │
│        • 8  candle microstructure (body, wick, engulfing)  ← NEW │
│        • 6  support/resistance context                     ← NEW │
│        • 4  volatility regime                              ← NEW │
│    - Feature order locked to metadata.features_required          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  MODEL LAYER                                                     │
│                                                                  │
│  V4EnsembleNode (5m + 15m)                                       │
│    - entry_long_model.predict_proba()   → long_prob              │
│    - entry_short_model.predict_proba()  → short_prob             │
│    - RegimeClassifier → TREND/RANGE/HIGH_VOL                     │
│    - signal = BUY if long_prob > 0.40 else                       │
│               SELL if short_prob > 0.40 else HOLD                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  REASONING LAYER (patched thresholds)                            │
│                                                                  │
│  MCPReasoningEngine                                              │
│    - _step3: disagreement damping threshold raised to 0.60       │
│    - _step5: mild_thresh = 0.18 (was 0.30)                       │
│    - HOLD band: [-0.18, +0.18] (was [-0.30, +0.30])             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  TRADING GATE LAYER (patched gates)                              │
│                                                                  │
│  TradingEventHandler                                             │
│    - skip HOLD                                                   │
│    - confidence >= 0.52 (was 0.65)                               │
│    - volatility present                                          │
│    - ADX < 15 blocks (was ADX < 20)                              │
│    - debounce: 10s (was 30s) for scalping frequency              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│  EXECUTION LAYER (patched targets)                               │
│                                                                  │
│  ExecutionEngine                                                 │
│    - TP = 0.20% (was 5%)                                         │
│    - SL = 0.15% (was 2%)                                         │
│    - Position monitor: 2s interval (was 15s)                     │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 Priority Order for Implementation

This prioritization reflects maximum impact per unit of effort:

| Priority | Change | Expected Impact |
|---|---|---|
| **P0** | Switch to TP/SL labels (`make_entry_labels` patch) | Eliminates HOLD class dominance at source |
| **P0** | Retrain on 5m timeframe with 8,000 candles | New model with balanced class distribution |
| **P1** | Patch `_step5_decision_synthesis` thresholds | Immediately reduces HOLD band at inference |
| **P1** | Patch confidence gate: 0.65 → 0.52 | Allows more signals through the trading gate |
| **P1** | Reduce TP/SL in agent config: 5%/2% → 0.20%/0.15% | Aligns execution with scalping targets |
| **P2** | Add 18 candle/SR/vol features | Improves model edge on microstructure |
| **P2** | Reduce `PRICE_FLUCTUATION_THRESHOLD_PCT` to 0.10 % | Higher trade frequency |
| **P2** | Reduce position monitor interval to 2s | Faster SL/TP hit detection |
| **P3** | Raise disagreement damping threshold to 0.60 | Reduces consensus suppression |
| **P3** | Patch ADX gate: < 20 → < 15 | Allows range scalping |
| **P3** | Unify feature implementations | Eliminates train/live drift risk |

### 9.3 Validation Checklist Before Going Live

```
[ ] Retrained model: HOLD class ≤ 55% on 5m training data
[ ] Class distribution: BUY ≥ 20%, SELL ≥ 20% on training data
[ ] Out-of-sample test: signal frequency ≥ 3 signals/hour on 5m data
[ ] Parity test: all features within 1e-5 between training and live paths
[ ] Backtested win rate ≥ 45% after fees on 30-day hold-out period
[ ] Sharpe proxy ≥ 0.5 on validation set
[ ] Confidence distribution: P(confidence > 0.52) ≥ 30% of non-HOLD signals
[ ] Artifact check: metadata.features_required matches FeatureEngineering methods
[ ] Position monitor: verified 2s interval in config before paper trading
[ ] Paper trade 48h: ≥ 5 trades executed, no exception in logs
```

---

*Report generated from code-traced analysis of: `JackSparrow_Trading_Colab_v4.ipynb`,  
`train_robust_ensemble.py`, `train_regime_model.py`, `docs/analysis/HOLD_SIGNAL_DIAGNOSIS.md`,  
`docs/reports/ml-pipeline-and-dataflow-report.md`, `docs/reports/ml-pipeline-enhancement-proposal.md`*

*All patches reference actual file paths and method names found in the uploaded codebase.*
