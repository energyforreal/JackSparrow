#!/usr/bin/env python3
"""
Standalone XGBoost classifier training script — Delta Exchange India.

Single-file script for training 15m / 1h / 4h XGBoost classifiers using the
canonical 50-feature list. Uses the Delta Exchange India public candles API
(no authentication required). Output bundles are compatible with the trading
agent's model discovery and XGBoostNode.

Usage:
  pip install xgboost ta pandas numpy requests scikit-learn
  python scripts/train_xgboost_standalone.py

Optional env:
  TRAIN_SAVE_DIR  — directory to save .pkl bundles (default: ./agent/model_storage/xgboost)
  TRAIN_SYMBOL    — symbol (default: BTCUSD)
  TRAIN_CANDLES   — candles per timeframe (default: 3000)
"""

from __future__ import annotations

import logging
import pickle
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests
import ta
from xgboost import XGBClassifier
from sklearn.metrics import classification_report
from sklearn.utils.class_weight import compute_sample_weight

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train_xgboost_standalone")

# -----------------------------------------------------------------------------
# Canonical 50-feature list (must match agent/data/feature_list.py)
# -----------------------------------------------------------------------------
FEATURE_LIST: List[str] = [
    # Price-based (16)
    "sma_10", "sma_20", "sma_50", "sma_100", "sma_200",
    "ema_12", "ema_26", "ema_50",
    "close_sma_20_ratio", "close_sma_50_ratio", "close_sma_200_ratio",
    "high_low_spread", "close_open_ratio", "body_size", "upper_shadow", "lower_shadow",
    # Momentum (10)
    "rsi_14", "rsi_7", "stochastic_k_14", "stochastic_d_14",
    "williams_r_14", "cci_20", "roc_10", "roc_20",
    "momentum_10", "momentum_20",
    # Trend (8)
    "macd", "macd_signal", "macd_histogram",
    "adx_14", "aroon_up", "aroon_down", "aroon_oscillator",
    "trend_strength",
    # Volatility (8)
    "bb_upper", "bb_lower", "bb_width", "bb_position",
    "atr_14", "atr_20",
    "volatility_10", "volatility_20",
    # Volume (6)
    "volume_sma_20", "volume_ratio", "obv",
    "volume_price_trend", "accumulation_distribution", "chaikin_oscillator",
    # Returns (2)
    "returns_1h", "returns_24h",
]
EXPECTED_FEATURE_COUNT = len(FEATURE_LIST)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_URL = "https://api.india.delta.exchange"
RESOLUTION_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d",
}
INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}

# Bars for returns_1h and returns_24h by resolution
RETURNS_1H_BARS = {"15m": 4, "1h": 1, "4h": 1}
RETURNS_24H_BARS = {"15m": 96, "1h": 24, "4h": 6}

BUY_THRESHOLD = 0.5
SELL_THRESHOLD = -0.5
XGB_PARAMS = dict(
    max_depth=6,
    learning_rate=0.05,
    n_estimators=300,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    objective="multi:softprob",
    num_class=3,
    random_state=42,
    eval_metric="mlogloss",
    early_stopping_rounds=20,
)


def fetch_candles_chunk(
    symbol: str,
    resolution: str,
    start: int,
    end: int,
    session: requests.Session,
    retries: int = 3,
) -> List[Dict]:
    """Fetch one chunk of candles. Public endpoint — no auth."""
    path = "/v2/history/candles"
    url = BASE_URL + path
    params = {
        "resolution": RESOLUTION_MAP[resolution],
        "symbol": symbol,
        "start": start,
        "end": end,
    }
    headers: Dict[str, str] = {"Accept": "application/json"}
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success") is False:
                raise ValueError(f"API error: {data}")
            result = data.get("result")
            if result is None:
                raise ValueError(f"API error: no result in response: {data}")
            if isinstance(result, dict):
                candles = result.get("candles", [])
            elif isinstance(result, list):
                candles = result
            else:
                raise ValueError(f"Unexpected result type: {type(result)}")
            return candles
        except Exception as exc:
            log.warning("Attempt %s/%s failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"All {retries} attempts failed for {symbol} {resolution}")


def fetch_historical_data(
    symbol: str,
    resolution: str,
    limit: int = 3000,
) -> pd.DataFrame:
    """Fetch `limit` candles and return OHLCV DataFrame."""
    if resolution not in INTERVAL_SECONDS:
        raise ValueError(f"Unsupported resolution {resolution!r}")
    step = INTERVAL_SECONDS[resolution]
    now = int(datetime.now(timezone.utc).timestamp())
    chunk_size = 500
    all_candles: List[Dict] = []
    end_ts = now
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    log.info("Fetching %s x %s candles for %s…", limit, resolution, symbol)
    while len(all_candles) < limit:
        fetch_n = min(chunk_size, limit - len(all_candles))
        start_ts = end_ts - fetch_n * step
        chunk = fetch_candles_chunk(symbol, resolution, start_ts, end_ts, session)
        if not chunk:
            log.info("No more historical data available.")
            break
        all_candles = chunk + all_candles
        end_ts = start_ts - step
        time.sleep(0.2)
    if not all_candles:
        raise RuntimeError(f"Zero candles returned for {symbol} {resolution}")
    df = pd.DataFrame(all_candles)
    df.rename(columns={"time": "timestamp"}, inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df.sort_values("timestamp", inplace=True)
    df.drop_duplicates("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    missing = [c for c in ["open", "high", "low", "close", "volume"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    log.info("Fetched %s candles — %s → %s", len(df), df["datetime"].iloc[0], df["datetime"].iloc[-1])
    return df


def add_features(df: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Compute all 50 canonical features. Uses high/low for Aroon (corrected)."""
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)

    # Price — SMAs
    for period in [10, 20, 50, 100, 200]:
        df[f"sma_{period}"] = ta.trend.SMAIndicator(c, window=period).sma_indicator()
    # EMAs
    df["ema_12"] = ta.trend.EMAIndicator(c, window=12).ema_indicator()
    df["ema_26"] = ta.trend.EMAIndicator(c, window=26).ema_indicator()
    df["ema_50"] = ta.trend.EMAIndicator(c, window=50).ema_indicator()
    # Ratios
    sma20 = df["sma_20"].replace(0, np.nan)
    sma50 = df["sma_50"].replace(0, np.nan)
    sma200 = df["sma_200"].replace(0, np.nan)
    df["close_sma_20_ratio"] = c / sma20
    df["close_sma_50_ratio"] = c / sma50
    df["close_sma_200_ratio"] = c / sma200
    df["high_low_spread"] = (h - l) / l.replace(0, np.nan)
    df["close_open_ratio"] = c / o.replace(0, np.nan)
    df["body_size"] = (c - o).abs() / o.replace(0, np.nan)
    df["upper_shadow"] = (h - np.maximum(o, c)) / h.replace(0, np.nan)
    df["lower_shadow"] = (np.minimum(o, c) - l) / l.replace(0, np.nan)

    # Momentum
    df["rsi_14"] = ta.momentum.RSIIndicator(c, window=14).rsi()
    df["rsi_7"] = ta.momentum.RSIIndicator(c, window=7).rsi()
    stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
    df["stochastic_k_14"] = stoch.stoch()
    df["stochastic_d_14"] = stoch.stoch_signal()
    df["williams_r_14"] = ta.momentum.WilliamsRIndicator(h, l, c, lbp=14).williams_r()
    df["cci_20"] = ta.trend.CCIIndicator(h, l, c, window=20).cci()
    df["roc_10"] = ta.momentum.ROCIndicator(c, window=10).roc()
    df["roc_20"] = ta.momentum.ROCIndicator(c, window=20).roc()
    df["momentum_10"] = c - c.shift(10)
    df["momentum_20"] = c - c.shift(20)

    # Trend — MACD
    macd = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()
    df["adx_14"] = ta.trend.ADXIndicator(h, l, c, window=14).adx()
    # Aroon: requires high and low (corrected)
    aroon = ta.trend.AroonIndicator(high=h, low=l, window=25)
    df["aroon_up"] = aroon.aroon_up()
    df["aroon_down"] = aroon.aroon_down()
    df["aroon_oscillator"] = aroon.aroon_indicator()
    df["trend_strength"] = (df["aroon_up"] - df["aroon_down"]).abs()

    # Volatility
    bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = bb.bollinger_wband()
    bb_diff = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["bb_position"] = (c - df["bb_lower"]) / bb_diff
    df["atr_14"] = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    df["atr_20"] = ta.volatility.AverageTrueRange(h, l, c, window=20).average_true_range()
    df["volatility_10"] = c.pct_change().rolling(10).std().fillna(0)
    df["volatility_20"] = c.pct_change().rolling(20).std().fillna(0)

    # Volume
    df["volume_sma_20"] = v.rolling(20).mean()
    df["volume_ratio"] = v / df["volume_sma_20"].replace(0, np.nan)
    df["obv"] = ta.volume.OnBalanceVolumeIndicator(c, v).on_balance_volume()
    # VPT
    vpt = (v * c.pct_change()).cumsum()
    df["volume_price_trend"] = vpt
    # A/D line
    mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    ad = (mfm * v).cumsum()
    df["accumulation_distribution"] = ad
    # Chaikin: EMA3(AD) - EMA10(AD)
    ad_ema3 = ad.ewm(span=3, adjust=False).mean()
    ad_ema10 = ad.ewm(span=10, adjust=False).mean()
    df["chaikin_oscillator"] = ad_ema3 - ad_ema10

    # Returns (resolution-dependent)
    p1 = RETURNS_1H_BARS.get(resolution, 4)
    p24 = RETURNS_24H_BARS.get(resolution, 96)
    df["returns_1h"] = c.pct_change(p1).fillna(0) * 100
    df["returns_24h"] = c.pct_change(p24).fillna(0) * 100

    return df


def create_labels(
    df: pd.DataFrame,
    forward_periods: int = 1,
    buy_threshold: float = BUY_THRESHOLD,
    sell_threshold: float = SELL_THRESHOLD,
) -> np.ndarray:
    """Labels: 0=SELL, 1=HOLD, 2=BUY."""
    future_close = df["close"].shift(-forward_periods)
    return_pct = (future_close - df["close"]) / df["close"].replace(0, np.nan) * 100
    labels = np.ones(len(df), dtype=int)
    labels[return_pct > buy_threshold] = 2
    labels[return_pct < sell_threshold] = 0
    labels[-forward_periods:] = 1
    return labels


def train_model(
    X: pd.DataFrame,
    y: np.ndarray,
    timeframe: str,
    xgb_params: dict,
) -> Tuple[XGBClassifier, Dict]:
    """Train XGBoost with 70/15/15 temporal split and class weights."""
    n = len(X)
    t1 = int(n * 0.70)
    t2 = int(n * 0.85)
    X_tr, y_tr = X.iloc[:t1], y[:t1]
    X_vl, y_vl = X.iloc[t1:t2], y[t1:t2]
    X_te, y_te = X.iloc[t2:], y[t2:]
    if len(X_vl) == 0 or len(X_te) == 0:
        raise ValueError(f"Not enough samples for split (n={n})")
    sw_tr = compute_sample_weight("balanced", y_tr)
    fit_params = {k: v for k, v in xgb_params.items() if k != "early_stopping_rounds"}
    early_stop = xgb_params.get("early_stopping_rounds", 20)
    model = XGBClassifier(**fit_params, early_stopping_rounds=early_stop)
    t0 = time.time()
    model.fit(
        X_tr, y_tr,
        sample_weight=sw_tr,
        eval_set=[(X_vl, y_vl)],
        verbose=50,
    )
    elapsed = time.time() - t0
    metrics = {
        "train_accuracy": float(model.score(X_tr, y_tr)),
        "val_accuracy": float(model.score(X_vl, y_vl)),
        "test_accuracy": float(model.score(X_te, y_te)),
        "training_time": round(elapsed, 2),
        "n_estimators_used": (
            model.best_iteration + 1
            if hasattr(model, "best_iteration") and model.best_iteration is not None
            else xgb_params["n_estimators"]
        ),
    }
    log.info(
        "[%s] train=%.4f  val=%.4f  test=%.4f  time=%ss",
        timeframe, metrics["train_accuracy"], metrics["val_accuracy"], metrics["test_accuracy"], metrics["training_time"]
    )
    y_pred = model.predict(X_te)
    print(f"\n── {timeframe} test-set report ──")
    print(classification_report(y_te, y_pred, target_names=["SELL", "HOLD", "BUY"], zero_division=0))
    return model, metrics


def save_model_bundle(
    model: XGBClassifier,
    symbol: str,
    timeframe: str,
    feature_cols: List[str],
    metrics: Dict,
    save_dir: Path,
) -> Path:
    """Save agent-compatible bundle (model, feature_cols, symbol, timeframe, metrics, trained_at)."""
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    fname = f"xgboost_classifier_{symbol}_{timeframe}.pkl"
    out_path = save_dir / fname
    if out_path.exists():
        bak = out_path.with_suffix(".pkl.bak")
        out_path.rename(bak)
        log.info("Backed up existing model to %s", bak)
    bundle = {
        "model": model,
        "feature_cols": feature_cols,
        "symbol": symbol,
        "timeframe": timeframe,
        "metrics": metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(out_path, "wb") as fh:
        pickle.dump(bundle, fh, protocol=pickle.HIGHEST_PROTOCOL)
    with open(out_path, "rb") as fh:
        loaded = pickle.load(fh)
    assert isinstance(loaded["model"], XGBClassifier)
    assert hasattr(loaded["model"], "predict_proba")
    dummy = np.random.rand(1, len(feature_cols))
    loaded["model"].predict(dummy)
    loaded["model"].predict_proba(dummy)
    log.info("Saved & verified → %s  (%s bytes)", out_path, out_path.stat().st_size)
    return out_path


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    save_dir = Path(
        __import__("os").environ.get(
            "TRAIN_SAVE_DIR",
            str(project_root / "agent" / "model_storage" / "xgboost"),
        )
    )
    symbol = __import__("os").environ.get("TRAIN_SYMBOL", "BTCUSD")
    candles_limit = int(__import__("os").environ.get("TRAIN_CANDLES", "3000"))
    timeframes = ["15m", "1h", "4h"]

    print("=" * 64)
    print(f"XGBoost training  |  symbol={symbol}  |  timeframes={timeframes}  |  save_dir={save_dir}")
    print("=" * 64)

    results = []
    for tf in timeframes:
        print(f"\n{'─' * 50}\n  Timeframe: {tf}\n{'─' * 50}")
        try:
            df = fetch_historical_data(symbol, tf, limit=candles_limit)
        except Exception as exc:
            print(f"✗ Data fetch failed for {tf}: {exc}")
            continue
        if len(df) < 500:
            print(f"✗ Only {len(df)} candles — need ≥500. Skipping.")
            continue
        df = add_features(df, tf)
        missing = [f for f in FEATURE_LIST if f not in df.columns]
        if missing:
            print(f"✗ Missing features: {missing}")
            continue
        df["label"] = create_labels(df)
        clean = df[FEATURE_LIST + ["label"]].dropna()
        if len(clean) < 200:
            print(f"✗ Only {len(clean)} clean rows after dropna. Skipping.")
            continue
        X = clean[FEATURE_LIST]
        y = clean["label"].values
        log.info("Features: %s, clean samples: %s", len(FEATURE_LIST), len(X))
        try:
            model, metrics = train_model(X, y, tf, XGB_PARAMS)
        except Exception as exc:
            print(f"✗ Training failed for {tf}: {exc}")
            import traceback
            traceback.print_exc()
            continue
        try:
            path = save_model_bundle(model, symbol, tf, FEATURE_LIST, metrics, save_dir)
            print(f"✓ Model saved → {path}")
        except Exception as exc:
            print(f"✗ Save failed: {exc}")
            continue
        results.append({"timeframe": tf, "samples": len(X), "features": len(FEATURE_LIST), **metrics, "path": str(path)})

    print("\n" + "=" * 64)
    print("Training complete.")
    print("=" * 64)
    if results:
        summary_path = save_dir / "training_summary.csv"
        pd.DataFrame(results).to_csv(summary_path, index=False)
        log.info("Summary saved → %s", summary_path)
    else:
        log.warning("No models were successfully trained.")
        sys.exit(1)


if __name__ == "__main__":
    main()
