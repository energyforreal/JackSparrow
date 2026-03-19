# 🧠 ML Pipeline Enhancement Proposal
## Trading Agent 2 — Deep Analysis & Candlestick/Chart Pattern Feature Architecture

**Author:** Architecture Review  
**Date:** 2026  
**Project:** Trading Agent 2 — XGBoost-Based Trading System  
**Scope:** Full pipeline audit + candlestick pattern recognition + chart pattern recognition

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Deep System Audit](#2-deep-system-audit)
   - 2.1 Architecture Assessment
   - 2.2 Feature Pipeline Drift (Root Cause Analysis)
   - 2.3 Model Training Weaknesses
   - 2.4 Inference Pipeline Issues
   - 2.5 Data Persistence Gap
3. [Proposed Fixes for Existing Gaps](#3-proposed-fixes-for-existing-gaps)
4. [Candlestick Pattern Feature Engineering](#4-candlestick-pattern-feature-engineering)
   - 4.1 Why Candlestick Patterns Matter for ML
   - 4.2 Complete Pattern Taxonomy
   - 4.3 Implementation Architecture
   - 4.4 Python Implementation Reference
5. [Chart Pattern Feature Engineering](#5-chart-pattern-feature-engineering)
   - 5.1 Why Chart Patterns Matter for ML
   - 5.2 Complete Pattern Taxonomy
   - 5.3 Implementation Architecture
   - 5.4 Python Implementation Reference
6. [Unified Feature Integration Plan](#6-unified-feature-integration-plan)
   - 6.1 New Expanded Feature Schema
   - 6.2 Unified Feature Pipeline Architecture
   - 6.3 Integration into Existing Codebase
7. [Labeling Strategy Overhaul](#7-labeling-strategy-overhaul)
8. [Training Pipeline Improvements](#8-training-pipeline-improvements)
9. [Risk & Validation Framework](#9-risk--validation-framework)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Final Recommendations Summary](#11-final-recommendations-summary)

---

## 1. Executive Summary

This document presents a thorough analysis of the Trading Agent 2 ML pipeline and a comprehensive proposal to significantly enhance its feature capability — specifically by introducing **candlestick pattern recognition** and **chart pattern recognition** as first-class ML features.

The core findings from the audit are:

| Problem | Severity | Impact |
|---|---|---|
| Feature pipeline mismatch (train vs live) | 🔴 Critical | Silent model degradation |
| Weak forward-return labeling | 🔴 Critical | Model predicts direction, not profit |
| No historical data persistence | 🔴 Critical | Non-reproducible training |
| Missing candlestick pattern features | 🟠 High | Missed entry/exit timing signals |
| Missing chart pattern features | 🟠 High | Missed structural market signals |
| v4 training code absent from repo | 🟠 High | Cannot verify train-inference parity |
| Redis single point of failure | 🟡 Medium | Full system outage on Redis crash |
| v4 fallback feature alignment | 🟡 Medium | Silent wrong-vector bug risk |

The proposed enhancements — when combined with the architectural fixes — are expected to meaningfully improve:
- Trade signal precision (fewer false positives)
- Entry timing quality (pattern-confirmed entries)
- Exit timing quality (reversal pattern awareness)
- Model interpretability

---

## 2. Deep System Audit

### 2.1 Architecture Assessment

The event-driven architecture is well-designed. The separation of concerns across:

```
MarketDataService → EventBus → FeatureServer → ModelRegistry → ReasoningEngine → TradingHandler → Execution
```

...is clean, scalable, and appropriate for a live trading system. The Redis Streams-based event bus with DLQ and retry logic is solid engineering.

**What works well:**
- Circuit breaker pattern in `DeltaExchangeClient`
- HMAC auth + timestamp drift handling
- Consensus engine in `MCPModelRegistry`
- Walk-forward OOF in `train_robust_ensemble.py`
- Chronological splits (no leakage found)
- v4 name-based feature alignment (when names present)
- Multi-model node architecture

### 2.2 Feature Pipeline Drift (Root Cause Analysis)

This is the most critical issue in the system. There are **two entirely separate implementations** of the same 50 features:

```
agent/data/feature_engineering.py     ← LIVE path
feature_store/feature_pipeline.py     ← TRAINING path
```

The divergence risk is real and grows over time. Specific scenarios where they silently drift:

**Rolling Window Edge Cases**
```python
# Training (vectorized pandas)
df['rsi_14'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

# Live (per-feature scalar)
closes = [c['close'] for c in candles[-100:]]
# If implementation differs by even one period offset → different RSI
```

**NaN Handling**
- `feature_pipeline.py` uses `fill_invalid=True` → fills NaN/Inf with 0
- `feature_engineering.py` has its own NaN handling per indicator
- If one fills differently → feature distributions shift at boundaries

**Indicator Library Differences**
- Training may use `ta` library (vectorized)
- Live may use direct numpy/pandas formulas
- These can produce numerically different results for edge periods

**Resolution-Dependent Features**
- `returns_1h` and `returns_24h` are calculated as `bars_1h = 60 // resolution_minutes` in training
- Live path must produce the same bar count — if it uses a fixed lookback instead, values differ

**Immediate Fix Required:** Create a single shared computation module (see Section 3).

### 2.3 Model Training Weaknesses

**The Labeling Problem**

Current label:
```python
future_return = (close[t+1] - close[t]) / close[t]
BUY  → return > 0.5%
SELL → return < -0.5%
HOLD → otherwise
```

This trains the model to predict **next-candle price direction**, NOT:
- Whether a trade at `t` would be profitable after fees
- Whether the move has enough momentum to reach a take-profit
- Whether a stop-loss would be triggered before a take-profit

A BUY signal that results in a 0.6% up-move is labeled correctly — but if fees are 0.1% each way and SL was 0.4% away, that trade loses money.

**Class Imbalance Not Addressed**
- In choppy markets, HOLD class dominates (60–70% of samples)
- XGBoost may learn to output HOLD to maximize accuracy
- No evidence of class weighting or SMOTE in the canonical training scripts

**No Regime Awareness in Training**
- The model is trained on all market conditions uniformly
- Trending and ranging features are mixed
- No regime label (trend/range/volatile) in the training data schema

### 2.4 Inference Pipeline Issues

**v4 Fallback Alignment Risk**

```python
# V4EnsembleNode._build_feature_vector()
# If feature_names missing or incomplete → slices first n features
feature_vector = feature_list[:n_expected]  # WRONG values, correct length
```

This silently produces a well-shaped but semantically wrong input vector. The model will give a confident but meaningless prediction. This must be converted to a hard failure with an alert.

**XGBoostNode Diagnostic Bug**
```python
# In xgboost_node.py — this crashes silently
if len(request.features) != 50:
    missing = set(request.features.keys())  # request.features is List[float], not dict
```

**Signal Freshness**
- `MAX_SIGNAL_AGE_SECONDS` gate exists — good
- But if feature computation takes > age threshold, trades are always blocked
- Need monitoring on feature computation latency

### 2.5 Data Persistence Gap

No raw candle storage means:
- Cannot reproduce training data
- Cannot audit what data a model was trained on
- Cannot run backtests on the exact same data
- Cannot incrementally train on new data without re-fetching

The `dataset_sha256` in robust ensemble metadata is excellent for fingerprinting but useless without the actual data being stored.

---

## 3. Proposed Fixes for Existing Gaps

### Fix 1: Unified Feature Computation Engine

Create a single source of truth for all feature computation:

```
feature_store/
└── unified_feature_engine.py    ← NEW: single implementation
    └── UnifiedFeatureEngine
        ├── compute_single(feature_name, candles_df) → float   (live path)
        └── compute_batch(candles_df) → DataFrame              (training path)
```

**Architecture:**
```python
# unified_feature_engine.py

class UnifiedFeatureEngine:
    """
    Single source of truth for all feature computation.
    Both live and training MUST use this class.
    """

    SUPPORTED_FEATURES = CANONICAL_50 + CANDLESTICK_PATTERNS + CHART_PATTERNS

    @staticmethod
    def _compute_rsi(closes: pd.Series, window: int = 14) -> pd.Series:
        """Internal: vectorized RSI — used by both batch and single modes."""
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(window).mean()
        loss = (-delta.clip(upper=0)).rolling(window).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def compute_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """Used during training. Returns full feature matrix."""
        out = pd.DataFrame(index=df.index)
        out['rsi_14'] = self._compute_rsi(df['close'], 14)
        # ... all 50+ features
        return out

    def compute_single(self, feature_name: str, candles: list) -> float:
        """Used during live inference. Returns latest scalar."""
        df = pd.DataFrame(candles)
        batch = self.compute_batch(df)
        return float(batch[feature_name].iloc[-1])
```

**Integration:**
- Replace `agent/data/feature_engineering.py` with a thin wrapper over `UnifiedFeatureEngine.compute_single()`
- Replace `feature_store/feature_pipeline.py` with a thin wrapper over `UnifiedFeatureEngine.compute_batch()`
- Add a parity test suite that runs both paths on the same data and asserts values match within tolerance

### Fix 2: Hard-Fail on Feature Alignment Issues

```python
# In V4EnsembleNode._build_feature_vector()
if not context.get("feature_names"):
    raise FeatureAlignmentError(
        "feature_names missing from context — cannot safely build feature vector. "
        "Refusing to use positional fallback to avoid silent semantic mismatch."
    )
```

### Fix 3: Historical Candle Persistence

```python
# New: data/candle_store.py
class CandleStore:
    """Persists raw OHLCV candles to Parquet + SQLite index."""

    def append(self, symbol: str, interval: str, candles: List[Dict]):
        df = pd.DataFrame(candles)
        path = self._parquet_path(symbol, interval)
        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df]).drop_duplicates('timestamp').sort_values('timestamp')
        df.to_parquet(path, index=False)

    def query(self, symbol: str, interval: str, start: int, end: int) -> pd.DataFrame:
        df = pd.read_parquet(self._parquet_path(symbol, interval))
        return df[(df['timestamp'] >= start) & (df['timestamp'] <= end)]
```

### Fix 4: Redis Fallback — Polling-Based Trigger

```python
# In market_data_service.py
async def _polling_fallback(self):
    """Activated when Redis event bus is unavailable."""
    while self._polling_active:
        try:
            candles = await self.get_market_data(...)
            if self._candle_closed(candles):
                await self._trigger_pipeline_directly(candles)
        except Exception as e:
            logger.error(f"Polling fallback error: {e}")
        await asyncio.sleep(self._poll_interval_seconds)
```

### Fix 5: Fix XGBoostNode Diagnostic Bug

```python
# xgboost_node.py — correct the mismatch logging
if len(request.features) != 50:
    expected = self.feature_names  # stored at load time
    actual_count = len(request.features)
    logger.error(
        f"Feature count mismatch: expected 50, got {actual_count}. "
        f"Expected features: {expected}"
    )
    raise FeatureCountError(f"Expected 50 features, got {actual_count}")
```

---

## 4. Candlestick Pattern Feature Engineering

### 4.1 Why Candlestick Patterns Matter for ML

Your current 50 features are all **indicator-derived scalars** — they summarize historical price behavior mathematically. Candlestick patterns capture something different: **price action psychology at the candle level**.

A Doji at a resistance level means something entirely different to a trend continuation signal than a Marubozu does. Importantly:

- Candlestick patterns encode **buyer vs seller momentum balance** at a specific moment
- They provide **timing signals** that lagging indicators miss
- They work as **confirming filters** — a BUY signal from RSI + a bullish engulfing candle is far more reliable than RSI alone
- XGBoost can learn **interaction effects** between pattern signals and indicator states

**For ML purposes**, candlestick patterns should be encoded as:
- **Binary flags** (1 = pattern present, 0 = not present) for single-candle patterns
- **Strength scores** (–1.0 to +1.0) for reliability-weighted patterns
- **Recency-weighted scores** for multi-candle sequences

### 4.2 Complete Pattern Taxonomy

#### Tier 1: Single-Candle Patterns (High Reliability)

| Pattern | Type | Direction | ML Encoding |
|---|---|---|---|
| Doji | Indecision | Neutral | `cdl_doji` ∈ {0, 1} |
| Long-legged Doji | Strong indecision | Neutral | `cdl_long_legged_doji` ∈ {0, 1} |
| Dragonfly Doji | Bullish reversal | Bullish | `cdl_dragonfly_doji` ∈ {0, 1} |
| Gravestone Doji | Bearish reversal | Bearish | `cdl_gravestone_doji` ∈ {0, 1} |
| Hammer | Bullish reversal | Bullish | `cdl_hammer` ∈ {0, 1} |
| Inverted Hammer | Potential bullish | Bullish | `cdl_inv_hammer` ∈ {0, 1} |
| Hanging Man | Bearish reversal | Bearish | `cdl_hanging_man` ∈ {0, 1} |
| Shooting Star | Bearish reversal | Bearish | `cdl_shooting_star` ∈ {0, 1} |
| Marubozu (Bull) | Strong bullish | Bullish | `cdl_bull_marubozu` ∈ {0, 1} |
| Marubozu (Bear) | Strong bearish | Bearish | `cdl_bear_marubozu` ∈ {0, 1} |
| Spinning Top | Indecision | Neutral | `cdl_spinning_top` ∈ {0, 1} |

#### Tier 2: Two-Candle Patterns (High Reliability)

| Pattern | Type | Direction | ML Encoding |
|---|---|---|---|
| Bullish Engulfing | Strong reversal | Bullish | `cdl_bull_engulfing` ∈ {0, 1} |
| Bearish Engulfing | Strong reversal | Bearish | `cdl_bear_engulfing` ∈ {0, 1} |
| Bullish Harami | Reversal | Bullish | `cdl_bull_harami` ∈ {0, 1} |
| Bearish Harami | Reversal | Bearish | `cdl_bear_harami` ∈ {0, 1} |
| Piercing Line | Bullish reversal | Bullish | `cdl_piercing` ∈ {0, 1} |
| Dark Cloud Cover | Bearish reversal | Bearish | `cdl_dark_cloud` ∈ {0, 1} |
| Tweezer Top | Bearish reversal | Bearish | `cdl_tweezer_top` ∈ {0, 1} |
| Tweezer Bottom | Bullish reversal | Bullish | `cdl_tweezer_bottom` ∈ {0, 1} |
| Kicker (Bull) | Strong continuation | Bullish | `cdl_bull_kicker` ∈ {0, 1} |
| Kicker (Bear) | Strong continuation | Bearish | `cdl_bear_kicker` ∈ {0, 1} |

#### Tier 3: Three-Candle Patterns

| Pattern | Type | Direction | ML Encoding |
|---|---|---|---|
| Morning Star | Strong reversal | Bullish | `cdl_morning_star` ∈ {0, 1} |
| Evening Star | Strong reversal | Bearish | `cdl_evening_star` ∈ {0, 1} |
| Three White Soldiers | Strong continuation | Bullish | `cdl_three_white_soldiers` ∈ {0, 1} |
| Three Black Crows | Strong continuation | Bearish | `cdl_three_black_crows` ∈ {0, 1} |
| Three Inside Up | Confirmation | Bullish | `cdl_three_inside_up` ∈ {0, 1} |
| Three Inside Down | Confirmation | Bearish | `cdl_three_inside_down` ∈ {0, 1} |
| Abandoned Baby (Bull) | Strong reversal | Bullish | `cdl_abandoned_baby_bull` ∈ {0, 1} |
| Abandoned Baby (Bear) | Strong reversal | Bearish | `cdl_abandoned_baby_bear` ∈ {0, 1} |

#### Tier 4: Composite / Derived Candlestick Features

These aggregate pattern signals into model-friendly scalars:

| Feature | Description | Range |
|---|---|---|
| `cdl_bull_score` | Weighted sum of all active bullish patterns | [0, 1] |
| `cdl_bear_score` | Weighted sum of all active bearish patterns | [0, 1] |
| `cdl_net_score` | `cdl_bull_score - cdl_bear_score` (net sentiment) | [–1, +1] |
| `cdl_reversal_signal` | Strongest reversal pattern strength at current price | [–1, +1] |
| `cdl_indecision_score` | Doji/spinning top cluster score | [0, 1] |
| `cdl_body_ratio` | Body size / total candle size | [0, 1] |
| `cdl_upper_wick_ratio` | Upper wick / total size | [0, 1] |
| `cdl_lower_wick_ratio` | Lower wick / total size | [0, 1] |
| `cdl_consecutive_bull` | Count of consecutive bullish closes | [0, N] |
| `cdl_consecutive_bear` | Count of consecutive bearish closes | [0, N] |

### 4.3 Implementation Architecture

```
feature_store/
└── pattern_features/
    ├── __init__.py
    ├── candlestick_patterns.py    ← All single/two/three candle patterns
    ├── chart_patterns.py          ← All chart structure patterns (Section 5)
    └── pattern_utils.py           ← Shared geometry/ATR helpers
```

The `CandlestickPatternEngine` plugs into the `UnifiedFeatureEngine` as a sub-module:

```
UnifiedFeatureEngine
├── _compute_rsi(...)
├── _compute_macd(...)
├── ...canonical indicators...
└── candlestick: CandlestickPatternEngine
    ├── detect_single_candle_patterns(df)
    ├── detect_two_candle_patterns(df)
    ├── detect_three_candle_patterns(df)
    └── compute_composite_scores(df)
```

### 4.4 Python Implementation Reference

```python
# feature_store/pattern_features/candlestick_patterns.py

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict

@dataclass
class CandleGeometry:
    """Pre-computed geometry for a single candle — avoids redundant calculations."""
    body: float          # abs(close - open)
    upper_wick: float    # high - max(open, close)
    lower_wick: float    # min(open, close) - low
    total_range: float   # high - low
    body_ratio: float    # body / total_range
    upper_ratio: float   # upper_wick / total_range
    lower_ratio: float   # lower_wick / total_range
    is_bullish: bool     # close > open

    @classmethod
    def from_row(cls, row: pd.Series) -> 'CandleGeometry':
        body = abs(row['close'] - row['open'])
        upper_wick = row['high'] - max(row['open'], row['close'])
        lower_wick = min(row['open'], row['close']) - row['low']
        total_range = row['high'] - row['low']
        safe_range = total_range if total_range > 1e-10 else 1e-10
        return cls(
            body=body, upper_wick=upper_wick, lower_wick=lower_wick,
            total_range=total_range, body_ratio=body / safe_range,
            upper_ratio=upper_wick / safe_range,
            lower_ratio=lower_wick / safe_range,
            is_bullish=row['close'] >= row['open']
        )


class CandlestickPatternEngine:
    """
    Detects candlestick patterns and produces ML-ready feature columns.
    All methods operate on a full OHLCV DataFrame and return a feature DataFrame
    aligned by index — safe for both training (batch) and live (last-row) use.
    """

    # Pattern weights for composite score (tunable)
    BULL_PATTERN_WEIGHTS = {
        'cdl_hammer': 0.8,
        'cdl_dragonfly_doji': 0.6,
        'cdl_bull_engulfing': 0.95,
        'cdl_bull_harami': 0.6,
        'cdl_piercing': 0.75,
        'cdl_morning_star': 0.9,
        'cdl_three_white_soldiers': 0.85,
        'cdl_bull_marubozu': 0.7,
        'cdl_tweezer_bottom': 0.65,
        'cdl_three_inside_up': 0.7,
        'cdl_abandoned_baby_bull': 0.95,
        'cdl_bull_kicker': 0.9,
        'cdl_inv_hammer': 0.5,
    }

    BEAR_PATTERN_WEIGHTS = {
        'cdl_shooting_star': 0.8,
        'cdl_gravestone_doji': 0.6,
        'cdl_bear_engulfing': 0.95,
        'cdl_bear_harami': 0.6,
        'cdl_dark_cloud': 0.75,
        'cdl_evening_star': 0.9,
        'cdl_three_black_crows': 0.85,
        'cdl_bear_marubozu': 0.7,
        'cdl_tweezer_top': 0.65,
        'cdl_three_inside_down': 0.7,
        'cdl_abandoned_baby_bear': 0.95,
        'cdl_bear_kicker': 0.9,
        'cdl_hanging_man': 0.7,
    }

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Main entry point. Returns DataFrame of all candlestick pattern features.
        Aligned with input df index.
        """
        required = ['open', 'high', 'low', 'close']
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        geo = df.apply(CandleGeometry.from_row, axis=1)
        out = pd.DataFrame(index=df.index)

        # ── Single-candle patterns ──────────────────────────────────────────
        out['cdl_doji'] = self._doji(df, geo)
        out['cdl_long_legged_doji'] = self._long_legged_doji(df, geo)
        out['cdl_dragonfly_doji'] = self._dragonfly_doji(df, geo)
        out['cdl_gravestone_doji'] = self._gravestone_doji(df, geo)
        out['cdl_hammer'] = self._hammer(df, geo)
        out['cdl_inv_hammer'] = self._inverted_hammer(df, geo)
        out['cdl_hanging_man'] = self._hanging_man(df, geo)
        out['cdl_shooting_star'] = self._shooting_star(df, geo)
        out['cdl_bull_marubozu'] = self._bull_marubozu(df, geo)
        out['cdl_bear_marubozu'] = self._bear_marubozu(df, geo)
        out['cdl_spinning_top'] = self._spinning_top(df, geo)

        # ── Two-candle patterns ─────────────────────────────────────────────
        out['cdl_bull_engulfing'] = self._bull_engulfing(df, geo)
        out['cdl_bear_engulfing'] = self._bear_engulfing(df, geo)
        out['cdl_bull_harami'] = self._bull_harami(df, geo)
        out['cdl_bear_harami'] = self._bear_harami(df, geo)
        out['cdl_piercing'] = self._piercing(df, geo)
        out['cdl_dark_cloud'] = self._dark_cloud(df, geo)
        out['cdl_tweezer_top'] = self._tweezer_top(df, geo)
        out['cdl_tweezer_bottom'] = self._tweezer_bottom(df, geo)
        out['cdl_bull_kicker'] = self._bull_kicker(df, geo)
        out['cdl_bear_kicker'] = self._bear_kicker(df, geo)

        # ── Three-candle patterns ───────────────────────────────────────────
        out['cdl_morning_star'] = self._morning_star(df, geo)
        out['cdl_evening_star'] = self._evening_star(df, geo)
        out['cdl_three_white_soldiers'] = self._three_white_soldiers(df, geo)
        out['cdl_three_black_crows'] = self._three_black_crows(df, geo)
        out['cdl_three_inside_up'] = self._three_inside_up(df, geo)
        out['cdl_three_inside_down'] = self._three_inside_down(df, geo)
        out['cdl_abandoned_baby_bull'] = self._abandoned_baby(df, geo, direction='bull')
        out['cdl_abandoned_baby_bear'] = self._abandoned_baby(df, geo, direction='bear')

        # ── Composite scores ────────────────────────────────────────────────
        out['cdl_bull_score'] = self._bull_composite(out)
        out['cdl_bear_score'] = self._bear_composite(out)
        out['cdl_net_score'] = out['cdl_bull_score'] - out['cdl_bear_score']
        out['cdl_reversal_signal'] = out['cdl_net_score'].clip(-1, 1)
        out['cdl_indecision_score'] = (
            out['cdl_doji'] * 0.6 + out['cdl_long_legged_doji'] * 0.8 + out['cdl_spinning_top'] * 0.4
        ).clip(0, 1)

        # ── Raw geometry features ───────────────────────────────────────────
        out['cdl_body_ratio'] = [g.body_ratio for g in geo]
        out['cdl_upper_wick_ratio'] = [g.upper_ratio for g in geo]
        out['cdl_lower_wick_ratio'] = [g.lower_ratio for g in geo]
        out['cdl_consecutive_bull'] = self._consecutive_direction(df, direction='bull')
        out['cdl_consecutive_bear'] = self._consecutive_direction(df, direction='bear')

        return out.fillna(0)

    # ── Single-candle detectors ─────────────────────────────────────────────

    def _doji(self, df, geo) -> pd.Series:
        """Body is < 10% of total range."""
        return pd.Series(
            [1 if g.body_ratio < 0.10 and g.total_range > 0 else 0 for g in geo],
            index=df.index
        )

    def _long_legged_doji(self, df, geo) -> pd.Series:
        """Doji with both wicks > 30% of range."""
        return pd.Series(
            [1 if g.body_ratio < 0.10 and g.upper_ratio > 0.30 and g.lower_ratio > 0.30 else 0
             for g in geo], index=df.index
        )

    def _dragonfly_doji(self, df, geo) -> pd.Series:
        """Doji with no upper wick, long lower wick."""
        return pd.Series(
            [1 if g.body_ratio < 0.10 and g.upper_ratio < 0.05 and g.lower_ratio > 0.60 else 0
             for g in geo], index=df.index
        )

    def _gravestone_doji(self, df, geo) -> pd.Series:
        """Doji with no lower wick, long upper wick."""
        return pd.Series(
            [1 if g.body_ratio < 0.10 and g.lower_ratio < 0.05 and g.upper_ratio > 0.60 else 0
             for g in geo], index=df.index
        )

    def _hammer(self, df, geo) -> pd.Series:
        """Lower wick ≥ 2× body, small upper wick, occurs after downtrend."""
        atr = df['close'].diff().abs().rolling(14).mean()
        return pd.Series([
            1 if (g.lower_wick >= 2.0 * g.body and g.upper_ratio < 0.20
                  and g.body_ratio > 0.05 and g.total_range > float(atr.iloc[i]) * 0.5)
            else 0
            for i, g in enumerate(geo)
        ], index=df.index)

    def _inverted_hammer(self, df, geo) -> pd.Series:
        """Upper wick ≥ 2× body, small lower wick."""
        return pd.Series(
            [1 if g.upper_wick >= 2.0 * g.body and g.lower_ratio < 0.20 and g.body_ratio > 0.05 else 0
             for g in geo], index=df.index
        )

    def _hanging_man(self, df, geo) -> pd.Series:
        """Same shape as hammer but detected after uptrend context."""
        # Shape-only; trend context added in composite scoring
        return pd.Series(
            [1 if g.lower_wick >= 2.0 * g.body and g.upper_ratio < 0.20 and g.body_ratio > 0.05 else 0
             for g in geo], index=df.index
        )

    def _shooting_star(self, df, geo) -> pd.Series:
        """Upper wick ≥ 2× body, small lower wick, bearish body preferred."""
        return pd.Series(
            [1 if g.upper_wick >= 2.0 * g.body and g.lower_ratio < 0.20
             and g.body_ratio > 0.05 and not g.is_bullish else 0
             for g in geo], index=df.index
        )

    def _bull_marubozu(self, df, geo) -> pd.Series:
        """Bullish candle, body > 95% of range (almost no wicks)."""
        return pd.Series(
            [1 if g.is_bullish and g.body_ratio > 0.95 else 0
             for g in geo], index=df.index
        )

    def _bear_marubozu(self, df, geo) -> pd.Series:
        """Bearish candle, body > 95% of range."""
        return pd.Series(
            [1 if not g.is_bullish and g.body_ratio > 0.95 else 0
             for g in geo], index=df.index
        )

    def _spinning_top(self, df, geo) -> pd.Series:
        """Small body (10–40%), wicks on both sides."""
        return pd.Series(
            [1 if 0.10 < g.body_ratio < 0.40 and g.upper_ratio > 0.20 and g.lower_ratio > 0.20 else 0
             for g in geo], index=df.index
        )

    # ── Two-candle detectors ────────────────────────────────────────────────

    def _bull_engulfing(self, df, geo) -> pd.Series:
        """
        Current bullish candle body fully engulfs previous bearish body.
        """
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            if (not prev.is_bullish and curr.is_bullish and
                    df['open'].iloc[i] <= df['close'].iloc[i-1] and
                    df['close'].iloc[i] >= df['open'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_engulfing(self, df, geo) -> pd.Series:
        """Current bearish candle body fully engulfs previous bullish body."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            if (prev.is_bullish and not curr.is_bullish and
                    df['open'].iloc[i] >= df['close'].iloc[i-1] and
                    df['close'].iloc[i] <= df['open'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bull_harami(self, df, geo) -> pd.Series:
        """Small bullish candle contained inside previous bearish candle."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            if (not prev.is_bullish and curr.is_bullish and
                    curr.body < prev.body * 0.5 and
                    df['open'].iloc[i] > df['close'].iloc[i-1] and
                    df['close'].iloc[i] < df['open'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_harami(self, df, geo) -> pd.Series:
        """Small bearish candle contained inside previous bullish candle."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            if (prev.is_bullish and not curr.is_bullish and
                    curr.body < prev.body * 0.5 and
                    df['open'].iloc[i] < df['close'].iloc[i-1] and
                    df['close'].iloc[i] > df['open'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _piercing(self, df, geo) -> pd.Series:
        """Bullish candle closes above midpoint of prior bearish candle."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            midpoint = (df['open'].iloc[i-1] + df['close'].iloc[i-1]) / 2
            if (not prev.is_bullish and curr.is_bullish and
                    df['open'].iloc[i] < df['close'].iloc[i-1] and
                    df['close'].iloc[i] > midpoint):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _dark_cloud(self, df, geo) -> pd.Series:
        """Bearish candle closes below midpoint of prior bullish candle."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            prev, curr = geo[i-1], geo[i]
            midpoint = (df['open'].iloc[i-1] + df['close'].iloc[i-1]) / 2
            if (prev.is_bullish and not curr.is_bullish and
                    df['open'].iloc[i] > df['close'].iloc[i-1] and
                    df['close'].iloc[i] < midpoint):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _tweezer_top(self, df, geo) -> pd.Series:
        """Two candles with nearly equal highs, second is bearish."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            high_diff = abs(df['high'].iloc[i] - df['high'].iloc[i-1])
            atr = df['close'].iloc[max(0,i-14):i].diff().abs().mean()
            if (not geo[i].is_bullish and high_diff < atr * 0.1):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _tweezer_bottom(self, df, geo) -> pd.Series:
        """Two candles with nearly equal lows, second is bullish."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            low_diff = abs(df['low'].iloc[i] - df['low'].iloc[i-1])
            atr = df['close'].iloc[max(0,i-14):i].diff().abs().mean()
            if (geo[i].is_bullish and low_diff < atr * 0.1):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bull_kicker(self, df, geo) -> pd.Series:
        """Gap up open after bearish candle, strong bullish follow-through."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            if (not geo[i-1].is_bullish and geo[i].is_bullish and
                    df['open'].iloc[i] > df['open'].iloc[i-1] and
                    geo[i].body_ratio > 0.5):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _bear_kicker(self, df, geo) -> pd.Series:
        """Gap down open after bullish candle, strong bearish follow-through."""
        result = [0] * len(df)
        for i in range(1, len(df)):
            if (geo[i-1].is_bullish and not geo[i].is_bullish and
                    df['open'].iloc[i] < df['open'].iloc[i-1] and
                    geo[i].body_ratio > 0.5):
                result[i] = 1
        return pd.Series(result, index=df.index)

    # ── Three-candle detectors ──────────────────────────────────────────────

    def _morning_star(self, df, geo) -> pd.Series:
        """Bearish → small/doji body → bullish that closes above midpoint of first."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            mid_a = (df['open'].iloc[i-2] + df['close'].iloc[i-2]) / 2
            if (not a.is_bullish and a.body_ratio > 0.4 and
                    b.body_ratio < 0.3 and
                    c.is_bullish and df['close'].iloc[i] > mid_a):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _evening_star(self, df, geo) -> pd.Series:
        """Bullish → small/doji body → bearish that closes below midpoint of first."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            mid_a = (df['open'].iloc[i-2] + df['close'].iloc[i-2]) / 2
            if (a.is_bullish and a.body_ratio > 0.4 and
                    b.body_ratio < 0.3 and
                    not c.is_bullish and df['close'].iloc[i] < mid_a):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_white_soldiers(self, df, geo) -> pd.Series:
        """Three consecutive bullish candles, each closing higher."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            if (a.is_bullish and b.is_bullish and c.is_bullish and
                    df['close'].iloc[i] > df['close'].iloc[i-1] > df['close'].iloc[i-2] and
                    a.body_ratio > 0.5 and b.body_ratio > 0.5 and c.body_ratio > 0.5):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_black_crows(self, df, geo) -> pd.Series:
        """Three consecutive bearish candles, each closing lower."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            if (not a.is_bullish and not b.is_bullish and not c.is_bullish and
                    df['close'].iloc[i] < df['close'].iloc[i-1] < df['close'].iloc[i-2] and
                    a.body_ratio > 0.5 and b.body_ratio > 0.5 and c.body_ratio > 0.5):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_inside_up(self, df, geo) -> pd.Series:
        """Bearish → Bullish Harami → Confirming bullish."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            if (not a.is_bullish and b.is_bullish and c.is_bullish and
                    b.body < a.body and df['close'].iloc[i] > df['close'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _three_inside_down(self, df, geo) -> pd.Series:
        """Bullish → Bearish Harami → Confirming bearish."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            if (a.is_bullish and not b.is_bullish and not c.is_bullish and
                    b.body < a.body and df['close'].iloc[i] < df['close'].iloc[i-1]):
                result[i] = 1
        return pd.Series(result, index=df.index)

    def _abandoned_baby(self, df, geo, direction: str) -> pd.Series:
        """Rare strong reversal: gap + doji + gap + continuation."""
        result = [0] * len(df)
        for i in range(2, len(df)):
            a, b, c = geo[i-2], geo[i-1], geo[i]
            is_doji_b = b.body_ratio < 0.10
            if direction == 'bull':
                gap1 = df['low'].iloc[i-1] < df['low'].iloc[i-2]
                gap2 = df['low'].iloc[i] > df['high'].iloc[i-1]
                if not a.is_bullish and is_doji_b and c.is_bullish and gap1 and gap2:
                    result[i] = 1
            else:
                gap1 = df['high'].iloc[i-1] > df['high'].iloc[i-2]
                gap2 = df['high'].iloc[i] < df['low'].iloc[i-1]
                if a.is_bullish and is_doji_b and not c.is_bullish and gap1 and gap2:
                    result[i] = 1
        return pd.Series(result, index=df.index)

    # ── Composite scoring ───────────────────────────────────────────────────

    def _bull_composite(self, out: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=out.index)
        for col, weight in self.BULL_PATTERN_WEIGHTS.items():
            if col in out.columns:
                score += out[col] * weight
        total_weight = sum(self.BULL_PATTERN_WEIGHTS.values())
        return (score / total_weight).clip(0, 1)

    def _bear_composite(self, out: pd.DataFrame) -> pd.Series:
        score = pd.Series(0.0, index=out.index)
        for col, weight in self.BEAR_PATTERN_WEIGHTS.items():
            if col in out.columns:
                score += out[col] * weight
        total_weight = sum(self.BEAR_PATTERN_WEIGHTS.values())
        return (score / total_weight).clip(0, 1)

    def _consecutive_direction(self, df: pd.DataFrame, direction: str) -> pd.Series:
        """Count of consecutive candles in the given direction."""
        is_bull = (df['close'] >= df['open']).astype(int)
        values = is_bull if direction == 'bull' else (1 - is_bull)
        result = []
        count = 0
        for v in values:
            count = count + 1 if v == 1 else 0
            result.append(count)
        return pd.Series(result, index=df.index)
```

---

## 5. Chart Pattern Feature Engineering

### 5.1 Why Chart Patterns Matter for ML

Chart patterns are **structural formations** visible across multiple candles (5–100+). They encode market psychology at a macro level:

- **Consolidation patterns** (triangles, flags): Market is building energy before a breakout
- **Reversal patterns** (H&S, double top/bottom): Trend exhaustion and change of direction
- **Continuation patterns** (flags, pennants, wedges): Trend pause before resumption

For ML specifically:
- Chart patterns encode **multi-candle context** that single indicators miss
- They provide **breakout probability estimates** — valuable for the current confidence-threshold logic
- They define **natural support/resistance zones** that the model currently has no awareness of
- XGBoost can learn to weight these signals conditionally on indicator state

### 5.2 Complete Pattern Taxonomy

#### Structural Reversal Patterns

| Pattern | Signal | Typical Bars | ML Feature |
|---|---|---|---|
| Head & Shoulders | Bearish reversal | 20–60 | `chp_hs_detected`, `chp_hs_neckline_dist` |
| Inverse H&S | Bullish reversal | 20–60 | `chp_ihs_detected`, `chp_ihs_neckline_dist` |
| Double Top | Bearish reversal | 15–50 | `chp_double_top`, `chp_double_top_dist` |
| Double Bottom | Bullish reversal | 15–50 | `chp_double_bottom`, `chp_double_bottom_dist` |
| Triple Top | Strong bearish | 25–80 | `chp_triple_top` |
| Triple Bottom | Strong bullish | 25–80 | `chp_triple_bottom` |
| Rounding Top | Bearish | 40–100 | `chp_rounding_top` |
| Rounding Bottom | Bullish | 40–100 | `chp_rounding_bottom` |

#### Continuation Patterns

| Pattern | Signal | Typical Bars | ML Feature |
|---|---|---|---|
| Bull Flag | Bullish continuation | 10–30 | `chp_bull_flag`, `chp_bull_flag_strength` |
| Bear Flag | Bearish continuation | 10–30 | `chp_bear_flag`, `chp_bear_flag_strength` |
| Bull Pennant | Bullish continuation | 10–25 | `chp_bull_pennant` |
| Bear Pennant | Bearish continuation | 10–25 | `chp_bear_pennant` |
| Ascending Triangle | Bullish breakout | 20–60 | `chp_asc_triangle`, `chp_asc_tri_breakout_dist` |
| Descending Triangle | Bearish breakout | 20–60 | `chp_desc_triangle`, `chp_desc_tri_breakout_dist` |
| Symmetrical Triangle | Neutral / breakout | 20–60 | `chp_sym_triangle`, `chp_triangle_apex_dist` |
| Rising Wedge | Bearish (reversal/continuation) | 20–60 | `chp_rising_wedge` |
| Falling Wedge | Bullish | 20–60 | `chp_falling_wedge` |
| Rectangle | Neutral (range) | 15–50 | `chp_rectangle`, `chp_rect_breakout_dir` |

#### Support / Resistance Features

| Feature | Description | Range |
|---|---|---|
| `sr_nearest_support` | Nearest support level below current price | price |
| `sr_nearest_resistance` | Nearest resistance level above current price | price |
| `sr_support_dist_pct` | % distance to nearest support | [0, N] |
| `sr_resistance_dist_pct` | % distance to nearest resistance | [0, N] |
| `sr_at_support` | Price is within ATR of a support zone | {0, 1} |
| `sr_at_resistance` | Price is within ATR of a resistance zone | {0, 1} |
| `sr_support_strength` | Number of touches on nearest support | [0, N] |
| `sr_resistance_strength` | Number of touches on nearest resistance | [0, N] |
| `sr_range_position` | Position within support-resistance range | [0, 1] |

#### Trendline Features

| Feature | Description | Range |
|---|---|---|
| `tl_uptrend_detected` | Uptrend line fitted with ≥3 touches | {0, 1} |
| `tl_downtrend_detected` | Downtrend line fitted with ≥3 touches | {0, 1} |
| `tl_trend_slope` | Slope of fitted trendline (normalized by ATR) | float |
| `tl_dist_to_trendline` | Distance from current price to nearest trendline | [0, N] |
| `tl_near_trendline` | Price within ATR of trendline | {0, 1} |
| `tl_breakout_up` | Price broke above downtrend line recently | {0, 1} |
| `tl_breakout_down` | Price broke below uptrend line recently | {0, 1} |

#### Breakout Detection Features

| Feature | Description | Range |
|---|---|---|
| `bo_range_high` | N-bar range high (lookback=20) | price |
| `bo_range_low` | N-bar range low (lookback=20) | price |
| `bo_at_high` | Price at/near N-bar high | {0, 1} |
| `bo_at_low` | Price at/near N-bar low | {0, 1} |
| `bo_volume_confirmation` | Volume spike on breakout candle | {0, 1} |
| `bo_breakout_score` | Combined breakout probability score | [0, 1] |

### 5.3 Implementation Architecture

```
feature_store/pattern_features/chart_patterns.py

ChartPatternEngine
├── detect_support_resistance(df, window=20) → sr_features
├── detect_trendlines(df, min_touches=3) → tl_features
├── detect_flag_patterns(df) → flag_features
├── detect_triangle_patterns(df) → triangle_features
├── detect_reversal_patterns(df) → reversal_features
└── detect_breakouts(df) → breakout_features
```

### 5.4 Python Implementation Reference

```python
# feature_store/pattern_features/chart_patterns.py

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from scipy.stats import linregress
from typing import Tuple, List, Optional


class ChartPatternEngine:
    """
    Detects chart patterns and computes structural market features.
    All methods return full-length DataFrames aligned with input index.
    """

    def compute_all(self, df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
        """Main entry point — computes all chart pattern features."""
        atr = self._compute_atr(df, atr_period)
        out = pd.DataFrame(index=df.index)

        sr = self._compute_support_resistance(df, atr)
        out = pd.concat([out, sr], axis=1)

        tl = self._compute_trendlines(df, atr)
        out = pd.concat([out, tl], axis=1)

        flags = self._compute_flags(df, atr)
        out = pd.concat([out, flags], axis=1)

        tri = self._compute_triangles(df, atr)
        out = pd.concat([out, tri], axis=1)

        rev = self._compute_reversal_patterns(df, atr)
        out = pd.concat([out, rev], axis=1)

        bo = self._compute_breakouts(df, atr)
        out = pd.concat([out, bo], axis=1)

        return out.fillna(0)

    # ── ATR (internal) ──────────────────────────────────────────────────────

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── Support & Resistance ────────────────────────────────────────────────

    def _compute_support_resistance(self, df: pd.DataFrame, atr: pd.Series,
                                    window: int = 5, lookback: int = 60) -> pd.DataFrame:
        """
        Identifies swing highs and lows as resistance/support clusters.
        Uses scipy argrelextrema for robust peak detection.
        """
        out = pd.DataFrame(index=df.index)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

        # Find local extrema
        high_idx = argrelextrema(highs, np.greater, order=window)[0]
        low_idx = argrelextrema(lows, np.less, order=window)[0]

        sr_support_dist = np.full(len(df), np.nan)
        sr_resistance_dist = np.full(len(df), np.nan)
        sr_at_support = np.zeros(len(df))
        sr_at_resistance = np.zeros(len(df))
        sr_support_strength = np.zeros(len(df))
        sr_resistance_strength = np.zeros(len(df))
        sr_range_position = np.full(len(df), 0.5)

        for i in range(lookback, len(df)):
            current_price = closes[i]
            current_atr = atr.iloc[i] if not np.isnan(atr.iloc[i]) else current_price * 0.01

            # Recent extrema within lookback
            recent_highs_idx = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            recent_lows_idx = low_idx[(low_idx >= i - lookback) & (low_idx < i)]

            if len(recent_highs_idx) > 0:
                resistance_levels = highs[recent_highs_idx]
                above = resistance_levels[resistance_levels > current_price]
                if len(above) > 0:
                    nearest_res = above.min()
                    sr_resistance_dist[i] = (nearest_res - current_price) / current_price * 100
                    sr_at_resistance[i] = 1 if abs(nearest_res - current_price) < current_atr else 0
                    # Strength = touches near this level
                    sr_resistance_strength[i] = np.sum(
                        np.abs(resistance_levels - nearest_res) < current_atr * 0.5
                    )

            if len(recent_lows_idx) > 0:
                support_levels = lows[recent_lows_idx]
                below = support_levels[support_levels < current_price]
                if len(below) > 0:
                    nearest_sup = below.max()
                    sr_support_dist[i] = (current_price - nearest_sup) / current_price * 100
                    sr_at_support[i] = 1 if abs(current_price - nearest_sup) < current_atr else 0
                    sr_support_strength[i] = np.sum(
                        np.abs(support_levels - nearest_sup) < current_atr * 0.5
                    )

            # Range position: 0 = at support, 1 = at resistance
            sup_d = sr_support_dist[i] if not np.isnan(sr_support_dist[i]) else 0
            res_d = sr_resistance_dist[i] if not np.isnan(sr_resistance_dist[i]) else 0
            total = sup_d + res_d
            if total > 0:
                sr_range_position[i] = res_d / total  # closer to resistance = higher value

        out['sr_support_dist_pct'] = sr_support_dist
        out['sr_resistance_dist_pct'] = sr_resistance_dist
        out['sr_at_support'] = sr_at_support
        out['sr_at_resistance'] = sr_at_resistance
        out['sr_support_strength'] = sr_support_strength
        out['sr_resistance_strength'] = sr_resistance_strength
        out['sr_range_position'] = sr_range_position

        return out

    # ── Trendlines ──────────────────────────────────────────────────────────

    def _compute_trendlines(self, df: pd.DataFrame, atr: pd.Series,
                             min_touches: int = 3, lookback: int = 50) -> pd.DataFrame:
        """
        Fits trendlines to recent swing highs (downtrend) and swing lows (uptrend).
        Reports slope, distance, and breakout signals.
        """
        out = pd.DataFrame(index=df.index)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

        high_idx = argrelextrema(highs, np.greater, order=5)[0]
        low_idx = argrelextrema(lows, np.less, order=5)[0]

        tl_uptrend = np.zeros(len(df))
        tl_downtrend = np.zeros(len(df))
        tl_slope = np.zeros(len(df))
        tl_dist = np.zeros(len(df))
        tl_near = np.zeros(len(df))
        tl_break_up = np.zeros(len(df))
        tl_break_down = np.zeros(len(df))

        for i in range(lookback, len(df)):
            current_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i] * 0.01

            # Uptrend: fit line through recent swing lows
            ul_idx = low_idx[(low_idx >= i - lookback) & (low_idx < i)]
            if len(ul_idx) >= min_touches:
                x = ul_idx.astype(float)
                y = lows[ul_idx]
                slope, intercept, r, _, _ = linregress(x, y)
                if slope > 0 and r > 0.7:
                    tl_uptrend[i] = 1
                    trendline_val = slope * i + intercept
                    dist = (closes[i] - trendline_val) / current_atr
                    tl_slope[i] = slope / (closes[i] * 0.0001)  # normalize
                    tl_dist[i] = max(0, dist)
                    tl_near[i] = 1 if abs(dist) < 1.0 else 0
                    # Breakout = price just dropped through uptrend line
                    if closes[i] < trendline_val and closes[i-1] >= (slope * (i-1) + intercept):
                        tl_break_down[i] = 1

            # Downtrend: fit line through recent swing highs
            dl_idx = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            if len(dl_idx) >= min_touches:
                x = dl_idx.astype(float)
                y = highs[dl_idx]
                slope, intercept, r, _, _ = linregress(x, y)
                if slope < 0 and r > 0.7:
                    tl_downtrend[i] = 1
                    trendline_val = slope * i + intercept
                    # Breakout = price just broke above downtrend line
                    if closes[i] > trendline_val and closes[i-1] <= (slope * (i-1) + intercept):
                        tl_break_up[i] = 1

        out['tl_uptrend_detected'] = tl_uptrend
        out['tl_downtrend_detected'] = tl_downtrend
        out['tl_trend_slope'] = tl_slope
        out['tl_dist_to_trendline'] = tl_dist
        out['tl_near_trendline'] = tl_near
        out['tl_breakout_up'] = tl_break_up
        out['tl_breakout_down'] = tl_break_down

        return out

    # ── Flag and Pennant Patterns ───────────────────────────────────────────

    def _compute_flags(self, df: pd.DataFrame, atr: pd.Series,
                       pole_bars: int = 10, flag_bars: int = 20) -> pd.DataFrame:
        """
        Detects bull/bear flags: sharp directional move (pole) followed by
        consolidation channel (flag) of opposite or neutral direction.
        """
        out = pd.DataFrame(index=df.index)
        closes = df['close'].values
        n = len(df)

        bull_flag = np.zeros(n)
        bear_flag = np.zeros(n)
        bull_flag_strength = np.zeros(n)
        bear_flag_strength = np.zeros(n)

        for i in range(pole_bars + flag_bars, n):
            current_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i]*0.01

            # Check for pole: strong directional move in pole_bars
            pole_start = i - pole_bars - flag_bars
            pole_end = i - flag_bars
            pole_move = closes[pole_end] - closes[pole_start]
            pole_magnitude = abs(pole_move) / (current_atr * pole_bars)

            if pole_magnitude > 0.5:  # significant pole
                flag_closes = closes[pole_end:i]
                flag_range = np.max(flag_closes) - np.min(flag_closes)
                flag_drift = closes[i-1] - closes[pole_end]

                if pole_move > 0:  # Bull pole
                    # Flag should be a slight downward or flat drift with narrow range
                    if flag_range < abs(pole_move) * 0.5 and flag_drift < 0:
                        bull_flag[i] = 1
                        bull_flag_strength[i] = pole_magnitude
                else:  # Bear pole
                    if flag_range < abs(pole_move) * 0.5 and flag_drift > 0:
                        bear_flag[i] = 1
                        bear_flag_strength[i] = pole_magnitude

        out['chp_bull_flag'] = bull_flag
        out['chp_bear_flag'] = bear_flag
        out['chp_bull_flag_strength'] = bull_flag_strength
        out['chp_bear_flag_strength'] = bear_flag_strength

        return out

    # ── Triangle Patterns ───────────────────────────────────────────────────

    def _compute_triangles(self, df: pd.DataFrame, atr: pd.Series,
                            lookback: int = 40) -> pd.DataFrame:
        """
        Detects ascending, descending, and symmetrical triangles
        using slope of high/low trendlines.
        """
        out = pd.DataFrame(index=df.index)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        n = len(df)

        asc_tri = np.zeros(n)
        desc_tri = np.zeros(n)
        sym_tri = np.zeros(n)
        apex_dist = np.zeros(n)

        for i in range(lookback, n):
            window_highs = highs[i-lookback:i]
            window_lows = lows[i-lookback:i]
            x = np.arange(lookback, dtype=float)

            slope_h, _, _, _, _ = linregress(x, window_highs)
            slope_l, _, _, _, _ = linregress(x, window_lows)

            # Ascending triangle: flat top, rising bottom
            if abs(slope_h) < 0.1 * float(atr.iloc[i]) and slope_l > 0:
                asc_tri[i] = 1

            # Descending triangle: flat bottom, falling top
            elif slope_h < 0 and abs(slope_l) < 0.1 * float(atr.iloc[i]):
                desc_tri[i] = 1

            # Symmetrical triangle: converging slopes
            elif slope_h < 0 and slope_l > 0:
                sym_tri[i] = 1
                # Approximate bars to apex
                price_range = window_highs[-1] - window_lows[-1]
                if abs(slope_h - slope_l) > 1e-10:
                    bars_to_apex = price_range / abs(slope_h - slope_l)
                    apex_dist[i] = bars_to_apex / lookback  # normalized

        out['chp_asc_triangle'] = asc_tri
        out['chp_desc_triangle'] = desc_tri
        out['chp_sym_triangle'] = sym_tri
        out['chp_triangle_apex_dist'] = apex_dist

        return out

    # ── Reversal Patterns ───────────────────────────────────────────────────

    def _compute_reversal_patterns(self, df: pd.DataFrame, atr: pd.Series,
                                    lookback: int = 60) -> pd.DataFrame:
        """
        Detects double top, double bottom (simplified geometric approach).
        Head & Shoulders uses peak-based geometry.
        """
        out = pd.DataFrame(index=df.index)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        n = len(df)

        double_top = np.zeros(n)
        double_bottom = np.zeros(n)
        double_top_dist = np.zeros(n)
        double_bottom_dist = np.zeros(n)
        hs_detected = np.zeros(n)
        ihs_detected = np.zeros(n)

        high_idx = argrelextrema(highs, np.greater, order=5)[0]
        low_idx = argrelextrema(lows, np.less, order=5)[0]

        for i in range(lookback, n):
            current_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else closes[i]*0.01

            # Double Top: two nearby highs at similar levels
            recent_hi = high_idx[(high_idx >= i - lookback) & (high_idx < i)]
            if len(recent_hi) >= 2:
                h1, h2 = highs[recent_hi[-2]], highs[recent_hi[-1]]
                separation = recent_hi[-1] - recent_hi[-2]
                if abs(h1 - h2) < current_atr * 0.5 and 5 <= separation <= lookback // 2:
                    double_top[i] = 1
                    double_top_dist[i] = (closes[i] - min(h1, h2)) / current_atr

            # Double Bottom: two nearby lows at similar levels
            recent_lo = low_idx[(low_idx >= i - lookback) & (low_idx < i)]
            if len(recent_lo) >= 2:
                l1, l2 = lows[recent_lo[-2]], lows[recent_lo[-1]]
                separation = recent_lo[-1] - recent_lo[-2]
                if abs(l1 - l2) < current_atr * 0.5 and 5 <= separation <= lookback // 2:
                    double_bottom[i] = 1
                    double_bottom_dist[i] = (max(l1, l2) - closes[i]) / current_atr

            # Head & Shoulders (simplified): 3 peaks, middle is highest
            if len(recent_hi) >= 3:
                p1, p2, p3 = highs[recent_hi[-3]], highs[recent_hi[-2]], highs[recent_hi[-1]]
                if p2 > p1 and p2 > p3 and abs(p1 - p3) < current_atr:
                    hs_detected[i] = 1

            # Inverse H&S: 3 troughs, middle is lowest
            if len(recent_lo) >= 3:
                t1, t2, t3 = lows[recent_lo[-3]], lows[recent_lo[-2]], lows[recent_lo[-1]]
                if t2 < t1 and t2 < t3 and abs(t1 - t3) < current_atr:
                    ihs_detected[i] = 1

        out['chp_double_top'] = double_top
        out['chp_double_bottom'] = double_bottom
        out['chp_double_top_dist'] = double_top_dist
        out['chp_double_bottom_dist'] = double_bottom_dist
        out['chp_hs_detected'] = hs_detected
        out['chp_ihs_detected'] = ihs_detected

        return out

    # ── Breakout Features ───────────────────────────────────────────────────

    def _compute_breakouts(self, df: pd.DataFrame, atr: pd.Series,
                            lookback: int = 20) -> pd.DataFrame:
        """
        Detects range-based breakouts with volume confirmation.
        """
        out = pd.DataFrame(index=df.index)
        closes = df['close'].values
        n = len(df)

        bo_at_high = np.zeros(n)
        bo_at_low = np.zeros(n)
        bo_volume_conf = np.zeros(n)
        bo_score = np.zeros(n)

        for i in range(lookback, n):
            window_closes = closes[i-lookback:i]
            range_high = np.max(window_closes)
            range_low = np.min(window_closes)
            current = closes[i]
            current_atr = float(atr.iloc[i]) if not np.isnan(atr.iloc[i]) else current*0.01

            # At/near range high
            if current >= range_high - current_atr * 0.3:
                bo_at_high[i] = 1

            # At/near range low
            if current <= range_low + current_atr * 0.3:
                bo_at_low[i] = 1

            # Volume confirmation if available
            if 'volume' in df.columns:
                vol = df['volume'].values
                avg_vol = np.mean(vol[i-lookback:i])
                if vol[i] > avg_vol * 1.5:
                    bo_volume_conf[i] = 1

            # Composite breakout score
            bo_score[i] = float(bo_at_high[i]) * 0.5 + float(bo_volume_conf[i]) * 0.5

        out['bo_at_high'] = bo_at_high
        out['bo_at_low'] = bo_at_low
        out['bo_volume_confirmation'] = bo_volume_conf
        out['bo_breakout_score'] = bo_score

        return out
```

---

## 6. Unified Feature Integration Plan

### 6.1 New Expanded Feature Schema

The expanded schema should be structured in tiers. Existing models continue to work on the canonical 50 while new models train on the full set.

```
CANONICAL_50          (existing — unchanged)
  + CANDLESTICK_40    (new — ~40 candlestick features)
  + CHART_PATTERNS_35 (new — ~35 chart pattern features)
  ─────────────────────────────────────────────────────
  = EXPANDED_125      (new full schema for next model generation)
```

**Candlestick feature names to register** (~40):
```python
CANDLESTICK_FEATURES = [
    # Single-candle
    'cdl_doji', 'cdl_long_legged_doji', 'cdl_dragonfly_doji', 'cdl_gravestone_doji',
    'cdl_hammer', 'cdl_inv_hammer', 'cdl_hanging_man', 'cdl_shooting_star',
    'cdl_bull_marubozu', 'cdl_bear_marubozu', 'cdl_spinning_top',
    # Two-candle
    'cdl_bull_engulfing', 'cdl_bear_engulfing', 'cdl_bull_harami', 'cdl_bear_harami',
    'cdl_piercing', 'cdl_dark_cloud', 'cdl_tweezer_top', 'cdl_tweezer_bottom',
    'cdl_bull_kicker', 'cdl_bear_kicker',
    # Three-candle
    'cdl_morning_star', 'cdl_evening_star', 'cdl_three_white_soldiers',
    'cdl_three_black_crows', 'cdl_three_inside_up', 'cdl_three_inside_down',
    'cdl_abandoned_baby_bull', 'cdl_abandoned_baby_bear',
    # Composite
    'cdl_bull_score', 'cdl_bear_score', 'cdl_net_score', 'cdl_reversal_signal',
    'cdl_indecision_score', 'cdl_body_ratio', 'cdl_upper_wick_ratio',
    'cdl_lower_wick_ratio', 'cdl_consecutive_bull', 'cdl_consecutive_bear',
]

CHART_PATTERN_FEATURES = [
    # Support/resistance
    'sr_support_dist_pct', 'sr_resistance_dist_pct',
    'sr_at_support', 'sr_at_resistance',
    'sr_support_strength', 'sr_resistance_strength', 'sr_range_position',
    # Trendlines
    'tl_uptrend_detected', 'tl_downtrend_detected', 'tl_trend_slope',
    'tl_dist_to_trendline', 'tl_near_trendline', 'tl_breakout_up', 'tl_breakout_down',
    # Flags
    'chp_bull_flag', 'chp_bear_flag', 'chp_bull_flag_strength', 'chp_bear_flag_strength',
    # Triangles
    'chp_asc_triangle', 'chp_desc_triangle', 'chp_sym_triangle', 'chp_triangle_apex_dist',
    # Reversals
    'chp_double_top', 'chp_double_bottom', 'chp_double_top_dist', 'chp_double_bottom_dist',
    'chp_hs_detected', 'chp_ihs_detected',
    # Breakouts
    'bo_at_high', 'bo_at_low', 'bo_volume_confirmation', 'bo_breakout_score',
]
```

### 6.2 Unified Feature Pipeline Architecture

```
feature_store/
├── unified_feature_engine.py          ← NEW: single computation source
├── feature_registry.py                ← UPDATED: add new feature names
├── feature_pipeline.py                ← UPDATED: thin wrapper over unified engine
├── feature_cache.py                   ← UPDATED: supports expanded schema
└── pattern_features/
    ├── __init__.py
    ├── candlestick_patterns.py        ← NEW
    ├── chart_patterns.py              ← NEW
    └── pattern_utils.py               ← NEW

agent/data/
├── feature_engineering.py            ← UPDATED: thin wrapper over unified engine
└── feature_server.py                 ← UPDATED: supports new feature names
```

**Backward Compatibility:** The canonical 50 feature names are unchanged. New models can declare `features_required = CANONICAL_50 + CANDLESTICK_FEATURES + CHART_PATTERN_FEATURES` in their metadata. Old models continue to use just the 50.

### 6.3 Integration into Existing Codebase

**Step 1: Feature Registration**
```python
# feature_store/feature_registry.py

from feature_store.pattern_features.candlestick_patterns import CANDLESTICK_FEATURES
from feature_store.pattern_features.chart_patterns import CHART_PATTERN_FEATURES

FEATURE_LIST = CANONICAL_50 + CANDLESTICK_FEATURES + CHART_PATTERN_FEATURES
EXPECTED_FEATURE_COUNT = len(FEATURE_LIST)  # ~125
```

**Step 2: UnifiedFeatureEngine Integration**
```python
# feature_store/unified_feature_engine.py

from feature_store.pattern_features.candlestick_patterns import CandlestickPatternEngine
from feature_store.pattern_features.chart_patterns import ChartPatternEngine

class UnifiedFeatureEngine:
    def __init__(self):
        self._cdl_engine = CandlestickPatternEngine()
        self._chp_engine = ChartPatternEngine()

    def compute_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self._compute_canonical_50(df)
        cdl = self._cdl_engine.compute_all(df)
        chp = self._chp_engine.compute_all(df)
        return pd.concat([out, cdl, chp], axis=1)[FEATURE_LIST]

    def compute_single(self, feature_name: str, candles: list) -> float:
        df = pd.DataFrame(candles)
        # Route to appropriate engine
        if feature_name in CANONICAL_50:
            return self._compute_single_canonical(feature_name, df)
        elif feature_name in CANDLESTICK_FEATURES:
            cdl = self._cdl_engine.compute_all(df)
            return float(cdl[feature_name].iloc[-1])
        elif feature_name in CHART_PATTERN_FEATURES:
            chp = self._chp_engine.compute_all(df)
            return float(chp[feature_name].iloc[-1])
        else:
            raise ValueError(f"Unknown feature: {feature_name}")
```

**Step 3: Live Feature Server Integration**
```python
# agent/data/feature_engineering.py (updated)

from feature_store.unified_feature_engine import UnifiedFeatureEngine

_engine = UnifiedFeatureEngine()

class FeatureEngineering:
    async def compute_feature(self, feature_name: str, candles: list) -> float:
        """Delegates entirely to unified engine — no separate implementation."""
        return _engine.compute_single(feature_name, candles)
```

**Step 4: Minimum Candle Requirement**

Pattern features need sufficient history. Update the feature server:
```python
# agent/data/feature_server.py
# Increase candle limit for pattern detection
CANDLES_FOR_PATTERNS = 200  # was 100 — needed for chart patterns with 60-bar lookbacks
```

---

## 7. Labeling Strategy Overhaul

### Current Problem

The model is trained on:
```
BUY if next_bar_return > 0.5%
```

This doesn't account for: fees, stop-loss, take-profit, or whether the move has enough momentum.

### Proposed: Trade Outcome Labeling

Replace with a **simulated trade outcome** label that mirrors actual execution:

```python
def create_trade_outcome_labels(
    df: pd.DataFrame,
    tp_pct: float = 0.015,    # 1.5% take-profit
    sl_pct: float = 0.008,    # 0.8% stop-loss
    fee_pct: float = 0.001,   # 0.1% per side
    max_bars: int = 20        # max trade duration
) -> pd.Series:
    """
    For each bar t, simulate a trade entry at close[t]:
    - Scan forward bars t+1 to t+max_bars
    - If TP hit first → BUY label (profitable long)
    - If SL hit first → SELL label (stop-loss on long)
    - If neither within max_bars → HOLD

    Also test the short side:
    - If SL-side hit first for a short → SELL label
    """
    labels = []
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values

    for i in range(len(df) - max_bars):
        entry = closes[i]
        tp_long = entry * (1 + tp_pct)
        sl_long = entry * (1 - sl_pct)

        label = 1  # HOLD default
        for j in range(1, max_bars + 1):
            if highs[i+j] >= tp_long:
                label = 2  # BUY — TP hit
                break
            if lows[i+j] <= sl_long:
                label = 0  # SELL — SL hit
                break

        labels.append(label)

    # Pad tail with HOLD
    labels.extend([1] * max_bars)
    return pd.Series(labels, index=df.index)
```

### Why This Matters

| Labeling Method | Model Learns | Actual Goal |
|---|---|---|
| Next-bar return | Direction of next candle | ❌ Not your goal |
| TP/SL outcome | Profitability of trade setup | ✅ Your actual goal |

---

## 8. Training Pipeline Improvements

### 8.1 Class Weight Balancing

Add to all training scripts:

```python
from collections import Counter
from sklearn.utils.class_weight import compute_class_weight

labels_array = y_train.values
class_weights = compute_class_weight('balanced', classes=np.unique(labels_array), y=labels_array)
scale_pos_weight = class_weights[2] / class_weights[1]  # BUY vs HOLD

model = XGBClassifier(
    scale_pos_weight=scale_pos_weight,  # or use sample_weight parameter
    ...
)
```

### 8.2 Regime-Aware Training

Add a market regime label to training data:

```python
def label_regime(df: pd.DataFrame, adx_threshold: float = 25.0) -> pd.Series:
    """
    0 = Ranging (ADX < 25)
    1 = Trending (ADX >= 25)
    2 = High Volatility (ATR z-score > 2)
    """
    adx = compute_adx(df)
    atr_zscore = (compute_atr(df) - compute_atr(df).rolling(50).mean()) / compute_atr(df).rolling(50).std()
    regime = pd.Series(0, index=df.index)
    regime[adx >= adx_threshold] = 1
    regime[atr_zscore > 2.0] = 2
    return regime
```

Then train a separate model per regime, or include `regime` as a feature.

### 8.3 Feature Importance Monitoring

After each training run, log feature importances:

```python
importances = pd.Series(model.feature_importances_, index=feature_names)

# Alert if new pattern features have near-zero importance
zero_importance_patterns = importances[
    (importances < 0.001) & (importances.index.str.startswith(('cdl_', 'chp_', 'sr_', 'tl_', 'bo_')))
]
if len(zero_importance_patterns) > 5:
    logger.warning(f"Many pattern features have near-zero importance: {list(zero_importance_patterns.index)}")
```

### 8.4 Parity Test Suite

Add a mandatory CI test before any training run:

```python
# tests/test_feature_parity.py

def test_feature_parity():
    """
    Verifies that batch (training path) and single (live path) produce
    identical values for the same input data.
    """
    candles = fetch_test_candles(n=200)
    df = pd.DataFrame(candles)

    engine = UnifiedFeatureEngine()
    batch_result = engine.compute_batch(df)

    for feature_name in FEATURE_LIST:
        batch_val = float(batch_result[feature_name].iloc[-1])
        single_val = engine.compute_single(feature_name, candles)
        assert abs(batch_val - single_val) < 1e-6, (
            f"Parity failure for {feature_name}: "
            f"batch={batch_val:.8f}, single={single_val:.8f}"
        )
```

---

## 9. Risk & Validation Framework

### 9.1 Pattern Feature Validation Rules

Before any pattern feature is used in production inference:

| Check | Rule |
|---|---|
| **Activation Rate** | Feature should activate on 2–30% of bars (otherwise: always-zero or always-one) |
| **Directional Alignment** | Bullish patterns should correlate positively with forward returns |
| **Parity** | Batch vs single value must match within 1e-6 |
| **Non-stationarity** | Feature distribution must not shift significantly over time |

```python
def validate_pattern_feature(feature_name: str, feature_series: pd.Series, 
                              future_returns: pd.Series) -> dict:
    activation_rate = feature_series.mean()
    directional_correlation = feature_series.corr(future_returns)
    return {
        'activation_rate': activation_rate,
        'directional_correlation': directional_correlation,
        'valid': (
            0.02 <= activation_rate <= 0.30 and
            abs(directional_correlation) > 0.02
        )
    }
```

### 9.2 Candle Count Guard

Pattern features need minimum candle history. Guard this at the feature server level:

```python
# agent/data/feature_server.py
PATTERN_FEATURE_PREFIXES = ('cdl_', 'chp_', 'sr_', 'tl_', 'bo_')
MIN_CANDLES_FOR_PATTERNS = 100  # chart patterns may need 60-bar lookback + buffer

async def get_features(self, feature_names, candles):
    has_patterns = any(
        name.startswith(PATTERN_FEATURE_PREFIXES) for name in feature_names
    )
    if has_patterns and len(candles) < MIN_CANDLES_FOR_PATTERNS:
        logger.warning(
            f"Insufficient candles for pattern features: {len(candles)} < {MIN_CANDLES_FOR_PATTERNS}. "
            "Pattern features will be set to 0."
        )
```

### 9.3 Backtest Validation Before Deployment

Before any new model with pattern features goes live:

1. Run on hold-out period (last 3 months not in training)
2. Compute Sharpe ratio, max drawdown, win rate
3. Compare to baseline (50-feature model)
4. Pattern-feature model must beat baseline on hold-out before promotion

---

## 10. Implementation Roadmap

### Phase 1 — Foundation Fixes (Week 1–2) 🔴 Critical

| Task | File(s) | Priority |
|---|---|---|
| Create `UnifiedFeatureEngine` | `feature_store/unified_feature_engine.py` | P0 |
| Update `feature_engineering.py` to wrap unified engine | `agent/data/feature_engineering.py` | P0 |
| Update `feature_pipeline.py` to wrap unified engine | `feature_store/feature_pipeline.py` | P0 |
| Add parity test suite | `tests/test_feature_parity.py` | P0 |
| Fix `V4EnsembleNode` fallback → hard-fail | `agent/models/v4_ensemble_node.py` | P0 |
| Fix `XGBoostNode` diagnostic bug | `agent/models/xgboost_node.py` | P1 |
| Add `CandleStore` for persistence | `agent/data/candle_store.py` | P1 |
| Add Redis polling fallback | `agent/data/market_data_service.py` | P1 |

### Phase 2 — Candlestick Pattern Features (Week 2–3) 🟠 High

| Task | File(s) |
|---|---|
| Implement `CandlestickPatternEngine` | `feature_store/pattern_features/candlestick_patterns.py` |
| Register `CANDLESTICK_FEATURES` in feature registry | `feature_store/feature_registry.py` |
| Add to `UnifiedFeatureEngine` | `feature_store/unified_feature_engine.py` |
| Validate activation rates on BTC historical data | Manual analysis |
| Retrain with new labeling strategy | `scripts/train_robust_ensemble.py` |

### Phase 3 — Chart Pattern Features (Week 3–5) 🟠 High

| Task | File(s) |
|---|---|
| Implement `ChartPatternEngine` | `feature_store/pattern_features/chart_patterns.py` |
| Implement S/R, trendline, flag, triangle, reversal, breakout | All within `ChartPatternEngine` |
| Register `CHART_PATTERN_FEATURES` | `feature_store/feature_registry.py` |
| Increase candle fetch limit to 200 | `agent/data/feature_server.py` |
| Run feature validation suite | `tests/test_pattern_validation.py` |

### Phase 4 — Model Retrain & Validate (Week 5–7) 🟡 Medium

| Task |
|---|
| Retrain with expanded 125-feature schema + TP/SL labeling |
| Run walk-forward backtest on hold-out period |
| Compare Sharpe, drawdown vs baseline 50-feature model |
| If metrics improve: promote new model to production discovery |
| If metrics don't improve: analyze feature importances, refine |

### Phase 5 — Production Hardening (Week 7–8)

| Task |
|---|
| Monitor pattern feature activation rates in live inference |
| Set up alerts for feature drift (distribution shift) |
| Add regime-aware model routing |
| Document the full expanded feature schema |

---

## 11. Final Recommendations Summary

### 🔴 Fix First (These Are Breaking Issues)

1. **Unify the feature pipeline.** Create `UnifiedFeatureEngine` and make both the live path and training path use it. This is the single most impactful fix in the system.

2. **Fix V4 fallback alignment.** The silent positional fallback must become a hard error. A feature-misaligned prediction is worse than no prediction.

3. **Persist candle data.** Without this, training is not reproducible and incremental training is impossible.

4. **Fix XGBoostNode diagnostic bug.** The mismatch logger crashes silently; it must log and raise cleanly.

### 🟠 High Impact (Feature Expansion)

5. **Add candlestick pattern features.** Start with the composite scores (`cdl_net_score`, `cdl_reversal_signal`) since they are dense signals suitable for XGBoost. Binary pattern flags can be added after validating activation rates.

6. **Add chart pattern features.** Priority order: S/R features first (most universally applicable), then trendlines, then flags/triangles. Reversal patterns (H&S, double top/bottom) need the most history — add last.

7. **Switch to TP/SL outcome labeling.** The model must learn what makes a trade profitable, not just which direction price moves next.

### 🟡 Model Architecture (Long-term)

8. **Train regime-aware models.** Candlestick and chart patterns behave very differently in trending vs ranging markets. A model that knows which regime it's in will use these features far more effectively.

9. **Validate everything before production.** Pattern features can appear to add signal in training but hurt live performance if they're overfitting to specific market regimes. The backtest validation gate (Phase 4) is not optional.

10. **Monitor feature drift in production.** Pattern activation rates in live inference should match training distribution. Large divergence = retraining signal.

---

> **Key Insight:** The XGBoost model itself is appropriate for this task. The opportunity lies entirely in the quality and richness of what is fed to it. Candlestick and chart pattern features represent exactly the kind of non-linear, context-dependent signal that XGBoost excels at learning — but only if they are computed consistently between training and inference, validated for statistical usefulness, and paired with a labeling strategy that reflects real trading outcomes.

---

*End of Report — Trading Agent 2 ML Enhancement Proposal*
