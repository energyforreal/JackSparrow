# System feedback: MTF layer, exits, timeframes

This doc captures the runtime design changes aligned with external review (Mar 2026).

## 1. Multi-timeframe decision engine

**Problem:** Several per-TF models without a single rule produced conflicting signals and weak `HOLD`/churn.

**Runtime fix:** `agent/core/mtf_decision_engine.py` + early return in `reasoning_engine._step5_decision_synthesis` when `MTF_DECISION_ENGINE_ENABLED=true`.

| Role | Default TF | Notes |
|------|------------|--------|
| Trend | `15m` | Direction gate |
| Entry | `5m` | Must confirm trend + `MTF_ENTRY_MIN_CONFIDENCE` |
| Filter | `3m` | Optional veto; set `MTF_FILTER_TIMEFRAME=none` to disable |

Fallback lists (`MTF_TREND_FALLBACK_TIMEFRAMES`, `MTF_ENTRY_FALLBACK_TIMEFRAMES`) apply if primary TFs are missing from loaded models.

## 2. Exit model off → rule-based exits

**Problem:** Exit classifiers showed ~0 F1 under severe label imbalance.

**Runtime fix:** `USE_ML_EXIT_MODEL=false` (default in `config`) skips exit `predict_proba` in `v4_ensemble_node`. Exits rely on **TP/SL**, **trailing stop**, and **max hold** in execution — tune via `TAKE_PROFIT_PERCENTAGE`, `STOP_LOSS_PERCENTAGE`, `TRAILING_STOP_PERCENTAGE`, `MAX_POSITION_HOLD_HOURS`.

## 3. Drop 1m from default stack

Default `TIMEFRAMES` is **`3m,5m,15m`**. Train/deploy models whose names end with those suffixes (e.g. `*_15m`) so the MTF mapper resolves them.

**Colab training:** `notebooks/JackSparrow_Trading_Colab_v4.ipynb` is aligned with the same stack: **`3m,5m,15m`**, **TP/SL entry labeling at 0.3% / 0.2%**, **no ML exit training/export**, and a pointer to `scripts/trade_simulator.py`. Reproducible edits live in `notebooks/_patch_jacksparrow_colab.py` if you need to re-apply from a clean copy.

**Artefacts:** new exports omit `exit_model` / `exit_scaler` in metadata; `V4EnsembleNode.from_metadata` accepts missing `exit_model` (optional path).

## 4. Objective: “profit after fees” (training / future)

Current models still optimize **directional classification**. Improving **expected net PnL after fees** is a **training/labeling** change (regression or cost-sensitive labels), not something the live agent infers without a new model head.

## 5. Trade-level simulation

`scripts/trade_simulator.py` — CSV OHLCV backtest with TP/SL, fees, and time exit. Use for sanity checks on parameters independent of sklearn metrics.

## 6. Feature filters at execution

`FEATURE_FILTER_ENABLED` + `BLOCK_BUY_NEAR_BB_UPPER_PCT`: in `trading_handler`, **BUY** / **STRONG_BUY** can be blocked when `bb_position` is near the upper band (resistance / chase risk).

## Env reference

See root `.env.example` for `MTF_*`, `USE_ML_EXIT_MODEL`, TP/SL defaults, and `TIMEFRAMES`.
