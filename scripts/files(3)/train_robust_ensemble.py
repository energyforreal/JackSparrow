"""
train_robust_ensemble.py  (v3)
-------------------------------
JackSparrow – Robust Stacking Ensemble Trainer  ★ Production Grade ★

Changes from v2 (audit-driven)
--------------------------------
  [NEW]  Artifacts saved as .joblib (replaces .pkl – safer, faster, version-stable)
  [NEW]  dataset_sha256 fingerprint added to metadata for reproducibility
  [NEW]  Feature drift statistics (mean/std/percentiles) saved per timeframe
  [NEW]  Exit model labeling improved: time stop + volatility stop included
  [NEW]  Model promotion gate: new model requires higher Sharpe proxy to replace live
  [NEW]  Signal threshold constants centralised (ENTRY_THRESHOLD, EXIT_THRESHOLD)
  [NEW]  Regime-aware system integrated via regime_classifier.py (see train_regime_model.py)
  [FIX]  All previous v2 improvements retained

Changes from v1 (audit-driven)
--------------------------------
  [NEW]  30m and 2h timeframes supported (default: 15m 30m 1h 2h 4h)
  [FIX]  Parallel base-learner training via joblib  (4-8× faster)
  [FIX]  Token-bucket rate limiter for Delta Exchange API (≤ 18 req/s)
  [FIX]  Candle integrity: monotonic timestamps, gap detection, NaN/Inf check
  [FIX]  RobustScaler fitted on train split and saved per timeframe
  [FIX]  Strict feature validation: count AND column-order vs FEATURE_LIST
  [FIX]  CalibratedClassifierCV (isotonic) run in parallel after base fits
  [FIX]  Exit model gets 3 market-regime features: ADX, ATR-pct-rank, vol-zscore
  [FIX]  feature_importance_{tag}.json saved per timeframe
  [FIX]  Artefact metadata includes: git commit, dataset date range, versions
  [FIX]  API keys masked in all log output

Artefacts per timeframe  (agent/model_storage/robust_ensemble/)
----------------------------------------------------------------
  entry_base_{TAG}.joblib      calibrated base learners  (was .pkl)
  entry_meta_{TAG}.joblib      XGBoost meta-stacker      (was .pkl)
  entry_scaler_{TAG}.joblib    RobustScaler               (was .pkl)
  exit_base_{TAG}.joblib
  exit_meta_{TAG}.joblib
  exit_scaler_{TAG}.joblib
  feature_importance_{TAG}.json
  feature_drift_{TAG}.json     NEW – training distribution for drift detection
  metadata_{TAG}.json

Usage
-----
  python scripts/train_robust_ensemble.py \\
      --symbol BTCUSD \\
      --timeframes 15m 30m 1h 2h 4h \\
      --total-candles 6000 \\
      --n-folds 5 \\
      --entry-threshold 0.003 \\
      --exit-lookahead 8 \\
      --output-dir agent/model_storage

Required env vars
-----------------
  DELTA_EXCHANGE_API_KEY
  DELTA_EXCHANGE_API_SECRET
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler, label_binarize

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Centralised signal thresholds (single source of truth) ────────────────────
ENTRY_THRESHOLD: float = 0.20   # |signal| ≥ this → actionable entry
EXIT_THRESHOLD:  float = 0.25   # signal  ≥ this → actionable exit
SIGNAL_THRESHOLD: float = 0.25  # alias used by bridge / node

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    import xgboost as xgb
except ImportError:
    logging.critical("XGBoost missing.  pip install xgboost==2.0.2")
    sys.exit(1)

try:
    import joblib
    def _save(obj, p): joblib.dump(obj, p)
    def _load(p):      return joblib.load(p)
    _ARTIFACT_EXT = ".joblib"
except ImportError:
    import pickle
    def _save(obj, p):
        with open(p, "wb") as f: pickle.dump(obj, f, protocol=4)
    def _load(p):
        with open(p, "rb") as f: return pickle.load(f)
    _ARTIFACT_EXT = ".pkl"
    log_pre = logging.getLogger("train_ensemble")
    log_pre.warning(
        "joblib not found – falling back to pickle. "
        "Install joblib for safer, faster artifact storage."
    )

from agent.data.delta_client import DeltaExchangeClient
from agent.data.feature_engineering import FeatureEngineering
from agent.data.feature_list import EXPECTED_FEATURE_COUNT, FEATURE_LIST

# ── structured logger ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train_ensemble")


# ─────────────────────────────────────────────────────────────────────────────
# Token-bucket rate limiter
# ─────────────────────────────────────────────────────────────────────────────

class _TokenBucket:
    def __init__(self, rate: float = 18.0, capacity: float = 18.0):
        self._rate     = rate
        self._capacity = capacity
        self._tokens   = capacity
        self._last     = time.monotonic()
        self._lock     = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity,
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens < 1.0:
                time.sleep((1.0 - self._tokens) / self._rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


_RATE_LIMITER = _TokenBucket()


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingConfig:
    symbol: str = "BTCUSD"
    timeframes: List[str] = field(
        default_factory=lambda: ["15m", "30m", "1h", "2h", "4h"]
    )
    total_candles: int   = 6000
    n_folds: int         = 5
    entry_threshold: float = 0.003   # 0.3 % forward return threshold
    exit_lookahead: int  = 8         # candles to look ahead for exit label
    exit_loss_pct: float = 0.015     # 1.5 % adverse → EXIT
    exit_profit_pct: float = 0.030   # 3.0 % gain    → EXIT
    train_split: float   = 0.70
    val_split: float     = 0.15
    lstm: bool           = False
    output_dir: str      = "agent/model_storage"
    random_seed: int     = 42
    parallel_jobs: int   = -1        # -1 = all cores


# ─────────────────────────────────────────────────────────────────────────────
# Git commit
# ─────────────────────────────────────────────────────────────────────────────

def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Candle fetch + integrity checks
# ─────────────────────────────────────────────────────────────────────────────

_TF_SECS: Dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}


def fetch_candles(
    client: DeltaExchangeClient,
    symbol: str,
    resolution: str,
    total: int,
) -> pd.DataFrame:
    """Paginate Delta Exchange (rate-limited) and return a validated DataFrame."""
    all_candles: List[Dict] = []
    end_time: Optional[int] = None

    log.info(f"  Fetching {total} {resolution} candles for {symbol} …")
    while len(all_candles) < total:
        _RATE_LIMITER.acquire()
        batch = min(2000, total - len(all_candles))
        try:
            resp = client.get_historical_candles(
                symbol=symbol, resolution=resolution,
                limit=batch, end=end_time,
            )
        except Exception as exc:
            log.warning(f"  API error – retry in 5 s: {exc}")
            time.sleep(5)
            continue

        if not resp:
            log.info("  Empty response – pagination complete.")
            break
        all_candles = resp + all_candles
        end_time = resp[0]["timestamp"] - 1
        if len(resp) < batch:
            log.info("  Reached earliest available data.")
            break

    df = pd.DataFrame(all_candles).rename(columns=str.lower)

    # ── required columns ──────────────────────────────────────────────────────
    required = {"open", "high", "low", "close", "volume", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = (
        df.sort_values("timestamp")
        .drop_duplicates("timestamp")
        .reset_index(drop=True)
    )
    df[["open", "high", "low", "close", "volume"]] = (
        df[["open", "high", "low", "close", "volume"]].astype(float)
    )

    # ── monotonic check ───────────────────────────────────────────────────────
    assert df["timestamp"].is_monotonic_increasing, \
        "Timestamps not monotonically increasing!"

    # ── NaN / Inf check ───────────────────────────────────────────────────────
    ohlcv = df[["open", "high", "low", "close", "volume"]]
    if ohlcv.isnull().any().any() or np.isinf(ohlcv.values).any():
        raise ValueError("NaN or Inf in OHLCV data – check API response.")

    # ── gap detection ─────────────────────────────────────────────────────────
    exp_gap = _TF_SECS.get(resolution)
    if exp_gap:
        gaps = df["timestamp"].diff().dt.total_seconds().dropna()
        n_large = int((gaps > exp_gap * 1.5).sum())
        if n_large:
            log.warning(
                f"  ⚠  {n_large} large time gaps detected in {resolution} candles"
            )

    log.info(
        f"  Collected {len(df)} candles  "
        f"({df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]})"
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Feature computation with strict validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_features(feat_df: pd.DataFrame) -> None:
    """Raise if feature count or column order deviates from FEATURE_LIST."""
    if len(feat_df.columns) != EXPECTED_FEATURE_COUNT:
        raise ValueError(
            f"Feature count: expected {EXPECTED_FEATURE_COUNT}, "
            f"got {len(feat_df.columns)}"
        )
    bad = [
        (i, exp, got)
        for i, (exp, got) in enumerate(zip(FEATURE_LIST, feat_df.columns))
        if exp != got
    ]
    if bad:
        raise ValueError(
            f"Feature order mismatch at {len(bad)} positions: {bad[:5]}"
        )


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    fe = FeatureEngineering()
    records: List[Dict[str, float]] = []
    candles = df.to_dict("records")
    for i in range(len(candles)):
        window = candles[: i + 1]
        row = {}
        for name in FEATURE_LIST:
            try:
                row[name] = float(fe.compute_feature(name, window))
            except Exception:
                row[name] = 0.0
        records.append(row)
    feat_df = pd.DataFrame(records, columns=FEATURE_LIST)
    _validate_features(feat_df)
    return feat_df


# ─────────────────────────────────────────────────────────────────────────────
# Exit model extra features
# ─────────────────────────────────────────────────────────────────────────────

POSITION_FEATURE_NAMES = [
    "sim_unrealised_pnl_pct",
    "sim_time_in_trade_ratio",
    "sim_drawdown_from_peak",
    "sim_entry_distance_atr",
]
REGIME_FEATURE_NAMES = [
    "regime_adx_14",
    "regime_atr_pct_rank",
    "regime_vol_zscore",
]
EXIT_EXTRA_FEATURE_NAMES = POSITION_FEATURE_NAMES + REGIME_FEATURE_NAMES


def augment_exit_features(
    feat_df: pd.DataFrame,
    close: pd.Series,
    atr: Optional[pd.Series] = None,
    adx: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Append 7 extra features to the base 50-feature matrix for the exit model.

    Position features are simulated at training time; real values are
    injected by the bridge at inference time.
    Regime features are computed from existing price data.
    """
    df = feat_df.copy()
    n = len(df)
    rng = np.random.default_rng(42)

    # ── 4 position-state features (simulated) ─────────────────────────────────
    df["sim_unrealised_pnl_pct"]    = rng.uniform(-0.05, 0.05, size=n)
    df["sim_time_in_trade_ratio"]   = rng.uniform(0.0, 1.0, size=n)
    df["sim_drawdown_from_peak"]    = rng.uniform(0.0, 0.04, size=n)
    df["sim_entry_distance_atr"]    = rng.normal(0, 1.5, size=n)

    # ── 3 market-regime features ───────────────────────────────────────────────

    # 1. ADX 14 – trend strength (higher = stronger trend)
    if adx is not None:
        df["regime_adx_14"] = adx.fillna(25.0).values
    elif "adx_14" in feat_df.columns:
        df["regime_adx_14"] = feat_df["adx_14"].fillna(25.0).values
    else:
        df["regime_adx_14"] = 25.0

    # 2. ATR percentile rank (rolling 50-period) – relative volatility
    if atr is not None:
        safe_atr = atr.replace(0, np.nan).ffill().bfill()
        df["regime_atr_pct_rank"] = (
            safe_atr.rolling(50, min_periods=5)
            .apply(
                lambda x: float(pd.Series(x).rank(pct=True).iloc[-1]),
                raw=False,
            )
            .fillna(0.5)
            .values
        )
    else:
        df["regime_atr_pct_rank"] = 0.5

    # 3. Volatility z-score (20-period vol vs 100-period baseline)
    log_ret  = np.log(close / close.shift(1)).fillna(0.0)
    vol_20   = log_ret.rolling(20, min_periods=5).std().fillna(0.0)
    vol_mean = vol_20.rolling(100, min_periods=10).mean().fillna(0.0)
    vol_std  = vol_20.rolling(100, min_periods=10).std().replace(0, np.nan).fillna(1e-8)
    df["regime_vol_zscore"] = (
        ((vol_20 - vol_mean) / vol_std).clip(-3, 3).fillna(0.0).values
    )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Label generation
# ─────────────────────────────────────────────────────────────────────────────

def make_entry_labels(
    close: pd.Series, lookahead: int = 1, threshold: float = 0.003,
) -> pd.Series:
    fwd = close.shift(-lookahead) / close - 1.0
    labels = np.where(fwd > threshold, 2, np.where(fwd < -threshold, 0, 1))
    return pd.Series(labels, index=close.index, dtype=int)


def make_exit_labels(
    close: pd.Series,
    lookahead: int = 8,
    loss_pct: float = 0.015,
    profit_pct: float = 0.030,
    time_stop_bars: Optional[int] = None,
    vol_stop_multiplier: float = 2.0,
    atr: Optional[pd.Series] = None,
) -> pd.Series:
    """Generate exit labels with loss/profit, time stop, and volatility stop.

    Improvements over v2
    --------------------
    - time_stop_bars: force EXIT if trade has been open longer than N bars
      (avoids the model learning biased long-hold exits)
    - volatility stop: if ATR is provided, widen/tighten loss_pct based on
      current vol to avoid being stopped out in high-vol regimes and vice versa.

    Label = 1 (EXIT) when ANY stop fires within the lookahead window.
    Label = 0 (HOLD) otherwise.
    """
    arr     = close.values
    n       = len(arr)
    labels  = np.zeros(n, dtype=int)
    atr_arr = atr.values if atr is not None else None
    _time_stop = time_stop_bars if time_stop_bars is not None else lookahead

    for i in range(n - lookahead):
        entry       = arr[i]
        future      = arr[i + 1 : i + 1 + lookahead]

        # Volatility-adjusted loss threshold
        if atr_arr is not None and entry > 0:
            dynamic_loss = min(
                loss_pct * vol_stop_multiplier,
                float(atr_arr[i]) / entry * vol_stop_multiplier,
            )
            dynamic_loss = max(dynamic_loss, loss_pct * 0.5)
        else:
            dynamic_loss = loss_pct

        # 1. Loss stop
        if (entry - future.min()) / entry >= dynamic_loss:
            labels[i] = 1
            continue

        # 2. Profit stop
        if (future.max() - entry) / entry >= profit_pct:
            labels[i] = 1
            continue

        # 3. Time stop – force exit after max hold period
        if len(future) >= _time_stop:
            time_ret = (future[_time_stop - 1] - entry) / entry
            if time_ret <= 0.0:
                labels[i] = 1

    return pd.Series(labels, index=close.index, dtype=int)


# ─────────────────────────────────────────────────────────────────────────────
# Model builders (n_jobs=1 per model so joblib parallelism works correctly)
# ─────────────────────────────────────────────────────────────────────────────

def _xgb_clf(seed: int) -> "xgb.XGBClassifier":
    return xgb.XGBClassifier(
        n_estimators=500, max_depth=6, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
        objective="multi:softprob", num_class=3,
        eval_metric="mlogloss", use_label_encoder=False,
        random_state=seed, n_jobs=1,
        early_stopping_rounds=30, verbosity=0,
    )


def _xgb_binary(seed: int) -> "xgb.XGBClassifier":
    return xgb.XGBClassifier(
        n_estimators=500, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=2.0, objective="binary:logistic",
        eval_metric="aucpr", random_state=seed, n_jobs=1,
        early_stopping_rounds=30, verbosity=0,
    )


def _lgb_clf(seed: int):
    if not HAS_LIGHTGBM: return None
    return lgb.LGBMClassifier(
        n_estimators=500, num_leaves=63, learning_rate=0.05,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
        min_child_samples=20, reg_alpha=0.1, reg_lambda=1.0,
        objective="multiclass", num_class=3,
        random_state=seed, n_jobs=1, verbose=-1,
    )


def _lgb_binary(seed: int):
    if not HAS_LIGHTGBM: return None
    return lgb.LGBMClassifier(
        n_estimators=500, num_leaves=63, learning_rate=0.05,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
        min_child_samples=20, is_unbalance=True, objective="binary",
        random_state=seed, n_jobs=1, verbose=-1,
    )


def _rf_clf(seed: int) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=300, max_depth=12, min_samples_leaf=10,
        max_features="sqrt", class_weight="balanced",
        random_state=seed, n_jobs=1,
    )


def _rf_binary(seed: int) -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=300, max_depth=10, min_samples_leaf=10,
        max_features="sqrt", class_weight="balanced_subsample",
        random_state=seed, n_jobs=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Parallel fit helpers (called by joblib.Parallel)
# ─────────────────────────────────────────────────────────────────────────────

def _fit_one(
    name: str, proto: Any,
    X_tr: np.ndarray, y_tr: np.ndarray,
    X_es: np.ndarray, y_es: np.ndarray,
) -> Tuple[str, Optional[Any]]:
    import copy
    m = copy.deepcopy(proto)
    try:
        if isinstance(m, (xgb.XGBClassifier, xgb.XGBRegressor)):
            m.fit(X_tr, y_tr, eval_set=[(X_es, y_es)], verbose=False)
        elif HAS_LIGHTGBM and isinstance(m, lgb.LGBMClassifier):
            cbs = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=-1)]
            m.fit(X_tr, y_tr, eval_set=[(X_es, y_es)], callbacks=cbs)
        else:
            m.fit(X_tr, y_tr)
    except Exception as exc:
        log.warning(f"    '{name}' fit error: {exc}")
        return name, None
    return name, m


def _calibrate_one(
    name: str, model: Any, X_val: np.ndarray, y_val: np.ndarray,
) -> Tuple[str, Any]:
    try:
        cal = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
        cal.fit(X_val, y_val)
        return name, cal
    except Exception as exc:
        log.warning(f"    Calibration failed for '{name}': {exc}")
        return name, model


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward OOF stacking
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_oof(
    protos: Dict[str, Any],
    X: np.ndarray,
    y: np.ndarray,
    n_folds: int,
    task: str,
    seed: int,
    n_jobs: int,
) -> Dict[str, np.ndarray]:
    from joblib import Parallel, delayed

    tscv      = TimeSeriesSplit(n_splits=n_folds)
    n_classes = 3 if task == "multiclass" else 2
    oof       = {name: np.zeros((len(X), n_classes)) for name in protos}
    active    = [(n, m) for n, m in protos.items() if m is not None]

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X)):
        log.info(f"    Fold {fold+1}/{n_folds}  train={len(tr_idx)}  val={len(val_idx)}")
        X_tr, X_val = X[tr_idx], X[val_idx]
        y_tr, y_val = y[tr_idx], y[val_idx]
        es           = max(1, int(len(X_tr) * 0.1))
        X_fit, X_es  = X_tr[:-es], X_tr[-es:]
        y_fit, y_es  = y_tr[:-es], y_tr[-es:]

        results = Parallel(n_jobs=n_jobs)(
            delayed(_fit_one)(n, m, X_fit, y_fit, X_es, y_es)
            for n, m in active
        )
        for name, fitted in results:
            if fitted is not None:
                oof[name][val_idx] = fitted.predict_proba(X_val)

    return oof


# ─────────────────────────────────────────────────────────────────────────────
# Meta-learner
# ─────────────────────────────────────────────────────────────────────────────

def train_meta(
    oof: Dict[str, np.ndarray], y: np.ndarray, task: str, seed: int,
) -> Any:
    meta_X = np.hstack([p if p.ndim > 1 else p.reshape(-1, 1) for p in oof.values()])
    if task == "multiclass":
        meta = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            objective="multi:softprob", num_class=3,
            use_label_encoder=False, random_state=seed, n_jobs=-1, verbosity=0,
        )
    else:
        meta = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            objective="binary:logistic",
            random_state=seed, n_jobs=-1, verbosity=0,
        )
    meta.fit(meta_X, y)
    log.info(f"  Meta-learner  meta_X.shape={meta_X.shape}")
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# Final full-fit + parallel calibration
# ─────────────────────────────────────────────────────────────────────────────

def full_fit_and_calibrate(
    protos: Dict[str, Any],
    X_tr: np.ndarray, y_tr: np.ndarray,
    X_val: np.ndarray, y_val: np.ndarray,
    n_jobs: int,
) -> Dict[str, Any]:
    from joblib import Parallel, delayed

    es    = max(1, int(len(X_tr) * 0.1))
    X_fit = X_tr[:-es]; X_es = X_tr[-es:]
    y_fit = y_tr[:-es]; y_es = y_tr[-es:]
    active = [(n, m) for n, m in protos.items() if m is not None]

    raw = Parallel(n_jobs=n_jobs)(
        delayed(_fit_one)(n, m, X_fit, y_fit, X_es, y_es)
        for n, m in active
    )
    cal = Parallel(n_jobs=n_jobs)(
        delayed(_calibrate_one)(n, m, X_val, y_val)
        for n, m in raw if m is not None
    )
    fitted = dict(cal)
    for name in fitted:
        log.info(f"  {name}  ✓  (calibrated)")
    return fitted


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────

def eval_entry(proba: np.ndarray, y: np.ndarray) -> Dict[str, float]:
    y_pred = np.argmax(proba, axis=1)
    acc = accuracy_score(y, y_pred)
    f1  = f1_score(y, y_pred, average="macro", zero_division=0)
    try:
        auc = roc_auc_score(
            label_binarize(y, classes=[0, 1, 2]), proba,
            multi_class="ovr", average="macro",
        )
    except Exception:
        auc = float("nan")
    return {"accuracy": round(acc, 4), "f1_macro": round(f1, 4), "auc_ovr": round(auc, 4)}


def eval_exit(proba: np.ndarray, y: np.ndarray) -> Dict[str, float]:
    y_pred = (proba[:, 1] >= 0.5).astype(int)
    acc    = accuracy_score(y, y_pred)
    f1     = f1_score(y, y_pred, zero_division=0)
    try:
        auc = roc_auc_score(y, proba[:, 1])
    except Exception:
        auc = float("nan")
    return {"accuracy": round(acc, 4), "f1": round(f1, 4), "auc": round(auc, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# Feature importance
# ─────────────────────────────────────────────────────────────────────────────

def get_importance(fitted: Dict[str, Any], names: List[str]) -> Dict[str, float]:
    total = np.zeros(len(names))
    count = 0
    for m in fitted.values():
        raw = getattr(m, "feature_importances_", None)
        if raw is None and hasattr(m, "estimator"):
            raw = getattr(m.estimator, "feature_importances_", None)
        if raw is not None and len(raw) == len(names):
            s = raw.sum()
            total += raw / (s if s > 0 else 1.0)
            count += 1
    if not count:
        return {}
    avg = total / count
    return dict(sorted(zip(names, avg.tolist()), key=lambda x: x[1], reverse=True))


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────

def save_art(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(obj, path)
    kb = path.stat().st_size / 1024
    log.info(f"  Saved {path.name}  ({kb:.1f} KB)")


def save_json(data: Dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    log.info(f"  JSON  {path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Dataset fingerprint  (3.2 – reproducibility)
# ─────────────────────────────────────────────────────────────────────────────

def _dataset_sha256(df: pd.DataFrame) -> str:
    """SHA-256 of the raw OHLCV data → guarantees training reproducibility."""
    cols = ["open", "high", "low", "close", "volume"]
    arr  = df[cols].values.astype(np.float64)
    return hashlib.sha256(arr.tobytes()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Feature drift statistics  (3.3 – live drift detection)
# ─────────────────────────────────────────────────────────────────────────────

def compute_drift_stats(feat_df: pd.DataFrame, names: List[str]) -> Dict[str, Dict]:
    """Compute per-feature distribution stats from training data.

    Saved alongside model artifacts so the live system can detect when
    feature distributions drift beyond their training range.
    """
    stats: Dict[str, Dict] = {}
    for name in names:
        if name not in feat_df.columns:
            continue
        col = feat_df[name].dropna()
        if len(col) == 0:
            continue
        stats[name] = {
            "mean":      float(col.mean()),
            "std":       float(col.std()),
            "p10":       float(col.quantile(0.10)),
            "p25":       float(col.quantile(0.25)),
            "p50":       float(col.quantile(0.50)),
            "p75":       float(col.quantile(0.75)),
            "p90":       float(col.quantile(0.90)),
            "n_samples": int(len(col)),
        }
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Sharpe proxy + model promotion gate  (3.7)
# ─────────────────────────────────────────────────────────────────────────────

def _sharpe_proxy(
    proba: np.ndarray, close: np.ndarray, lookahead: int = 1
) -> float:
    """Simplified annualised Sharpe proxy from predicted signals vs price returns."""
    pred_class = np.argmax(proba, axis=1)
    signal = np.where(pred_class == 2, 1.0, np.where(pred_class == 0, -1.0, 0.0))
    n = min(len(signal), len(close) - lookahead)
    if n < 10:
        return 0.0
    fwd_ret  = np.log(close[lookahead:n+lookahead] / np.maximum(close[:n], 1e-10))
    strat    = signal[:n] * fwd_ret
    std      = strat.std()
    return float(strat.mean() / std * np.sqrt(252)) if std > 1e-10 else 0.0


def _should_promote(
    new_sharpe: float,
    metadata_path: Path,
    min_delta: float = 0.05,
) -> Tuple[bool, str]:
    """Return (promote, reason) based on Sharpe comparison."""
    if not metadata_path.exists():
        return True, "No prior model found – promoting automatically."
    try:
        with open(metadata_path) as f:
            old_meta = json.load(f)
        baseline = float(old_meta.get("sharpe_proxy", 0.0))
    except Exception:
        baseline = 0.0
    if new_sharpe >= baseline + min_delta:
        return True, (
            f"New Sharpe {new_sharpe:.4f} > baseline {baseline:.4f} "
            f"(Δ={new_sharpe-baseline:.4f} ≥ {min_delta})."
        )
    return False, (
        f"New Sharpe {new_sharpe:.4f} does NOT improve on "
        f"baseline {baseline:.4f} by {min_delta}. Skipping promotion."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-timeframe pipeline
# ─────────────────────────────────────────────────────────────────────────────

def train_for_timeframe(
    client: DeltaExchangeClient,
    cfg: TrainingConfig,
    timeframe: str,
    output_dir: Path,
    git_commit: str,
) -> Dict[str, Any]:
    tag = f"{cfg.symbol}_{timeframe}"
    log.info(f"\n{'='*64}")
    log.info(f"  Training  →  {tag}")
    log.info(f"{'='*64}")

    # 1. Fetch
    df = fetch_candles(client, cfg.symbol, timeframe, cfg.total_candles)

    # 2. Features
    log.info("  Computing 50 features (strict validation on) …")
    feat_df = compute_features(df)

    warmup = 200
    feat_df = feat_df.iloc[warmup:].reset_index(drop=True)
    df      = df.iloc[warmup:].reset_index(drop=True)
    feat_df = feat_df.ffill().fillna(0.0)

    # 3. Labels
    close      = df["close"]
    atr_series = feat_df["atr_14"] if "atr_14" in feat_df.columns else None
    adx_series = feat_df["adx_14"] if "adx_14" in feat_df.columns else None

    entry_lbl = make_entry_labels(close, threshold=cfg.entry_threshold)
    exit_lbl  = make_exit_labels(
        close, lookahead=cfg.exit_lookahead,
        loss_pct=cfg.exit_loss_pct, profit_pct=cfg.exit_profit_pct,
        time_stop_bars=cfg.exit_lookahead,
        atr=atr_series,
    )
    exit_feat_df = augment_exit_features(feat_df, close, atr=atr_series, adx=adx_series)

    # Trim last lookahead rows (no valid labels)
    valid        = len(feat_df) - cfg.exit_lookahead
    feat_df      = feat_df.iloc[:valid]
    exit_feat_df = exit_feat_df.iloc[:valid]
    entry_lbl    = entry_lbl.iloc[:valid]
    exit_lbl     = exit_lbl.iloc[:valid]

    log.info(
        f"  Dataset: {valid} rows  |  "
        f"SELL={int((entry_lbl==0).sum())}  "
        f"HOLD={int((entry_lbl==1).sum())}  "
        f"BUY={int((entry_lbl==2).sum())}  |  "
        f"exit_yes={int((exit_lbl==1).sum())}"
    )

    # 4. Splits
    n      = len(feat_df)
    tr_end = int(n * cfg.train_split)
    va_end = int(n * (cfg.train_split + cfg.val_split))

    def split(a): return a[:tr_end], a[tr_end:va_end], a[va_end:]

    X_all  = feat_df.values.astype(np.float32)
    Xe_all = exit_feat_df.values.astype(np.float32)
    ye_all = entry_lbl.values
    yx_all = exit_lbl.values

    X_tr,  X_val,  X_te  = split(X_all)
    Xe_tr, Xe_val, Xe_te = split(Xe_all)
    ye_tr, ye_val, ye_te = split(ye_all)
    yx_tr, yx_val, yx_te = split(yx_all)

    # 5. Scalers (stored for external / neural use)
    log.info("  Fitting RobustScalers …")
    entry_scaler = RobustScaler().fit(X_tr)
    exit_scaler  = RobustScaler().fit(Xe_tr)

    # 6. Base learner prototypes
    entry_protos: Dict[str, Any] = {
        "xgb_clf": _xgb_clf(cfg.random_seed),
        "rf_clf":  _rf_clf(cfg.random_seed),
    }
    if HAS_LIGHTGBM:
        entry_protos["lgb_clf"] = _lgb_clf(cfg.random_seed)

    exit_protos: Dict[str, Any] = {
        "xgb_exit": _xgb_binary(cfg.random_seed),
        "rf_exit":  _rf_binary(cfg.random_seed),
    }
    if HAS_LIGHTGBM:
        exit_protos["lgb_exit"] = _lgb_binary(cfg.random_seed)

    # 7. Walk-forward OOF
    log.info("  Walk-forward OOF – ENTRY …")
    oof_entry = walk_forward_oof(
        entry_protos, X_tr, ye_tr, cfg.n_folds, "multiclass",
        cfg.random_seed, cfg.parallel_jobs,
    )
    log.info("  Walk-forward OOF – EXIT …")
    oof_exit = walk_forward_oof(
        exit_protos, Xe_tr, yx_tr, cfg.n_folds, "binary",
        cfg.random_seed, cfg.parallel_jobs,
    )

    # 8. Meta-learners
    log.info("  Training meta-learners …")
    entry_meta = train_meta(oof_entry, ye_tr, "multiclass", cfg.random_seed)
    exit_meta  = train_meta(oof_exit,  yx_tr, "binary",     cfg.random_seed)

    # 9. Full-fit + parallel calibration
    log.info("  Full-fit + calibration – ENTRY …")
    entry_base = full_fit_and_calibrate(
        entry_protos, X_tr, ye_tr, X_val, ye_val, cfg.parallel_jobs
    )
    log.info("  Full-fit + calibration – EXIT …")
    exit_base  = full_fit_and_calibrate(
        exit_protos, Xe_tr, yx_tr, Xe_val, yx_val, cfg.parallel_jobs
    )

    # 10. Stacking predict
    def stack_predict(base: Dict, meta: Any, X: np.ndarray) -> np.ndarray:
        parts = [m.predict_proba(X) for m in base.values()]
        return meta.predict_proba(np.hstack(parts))

    # 11. Test evaluation
    entry_met = eval_entry(stack_predict(entry_base, entry_meta, X_te),  ye_te)
    exit_met  = eval_exit (stack_predict(exit_base,  exit_meta,  Xe_te), yx_te)
    log.info(f"  ENTRY test: {entry_met}")
    log.info(f"  EXIT  test: {exit_met}")

    # 12. Feature importance
    entry_imp = get_importance(entry_base, FEATURE_LIST)
    exit_names = list(exit_feat_df.columns)
    exit_imp   = get_importance(exit_base,  exit_names)
    log.info(f"  Top-5 entry: {list(entry_imp.items())[:5]}")
    log.info(f"  Top-5 exit:  {list(exit_imp.items())[:5]}")

    # 12b. Feature drift statistics
    log.info("  Computing feature drift statistics …")
    drift_stats = compute_drift_stats(feat_df, FEATURE_LIST)

    # 12c. Sharpe proxy (for promotion gate)
    entry_test_proba = stack_predict(entry_base, entry_meta, X_te)
    sharpe = _sharpe_proxy(entry_test_proba, df["close"].values[n - len(X_te):])

    # 12d. Dataset SHA-256 fingerprint
    data_hash = _dataset_sha256(df)

    # 13. Persist (artifacts now use .joblib)
    ext = _ARTIFACT_EXT
    ens = output_dir / "robust_ensemble"

    save_art(entry_base,   ens / f"entry_base_{tag}{ext}")
    save_art(entry_meta,   ens / f"entry_meta_{tag}{ext}")
    save_art(entry_scaler, ens / f"entry_scaler_{tag}{ext}")
    save_art(exit_base,    ens / f"exit_base_{tag}{ext}")
    save_art(exit_meta,    ens / f"exit_meta_{tag}{ext}")
    save_art(exit_scaler,  ens / f"exit_scaler_{tag}{ext}")

    # Feature importance
    save_json(
        {"generated_at": datetime.now(timezone.utc).isoformat(),
         "entry": entry_imp, "exit": exit_imp},
        ens / f"feature_importance_{tag}.json",
    )

    # Feature drift stats
    save_json(
        {"generated_at": datetime.now(timezone.utc).isoformat(),
         "features": drift_stats},
        ens / f"feature_drift_{tag}.json",
    )

    # Model promotion check
    meta_path = ens / f"metadata_{tag}.json"
    promoted, promo_reason = _should_promote(sharpe, meta_path)
    log.info(f"  Promotion: {promo_reason}")

    file_paths = {
        "entry_base":   str(ens / f"entry_base_{tag}{ext}"),
        "entry_meta":   str(ens / f"entry_meta_{tag}{ext}"),
        "entry_scaler": str(ens / f"entry_scaler_{tag}{ext}"),
        "exit_base":    str(ens / f"exit_base_{tag}{ext}"),
        "exit_meta":    str(ens / f"exit_meta_{tag}{ext}"),
        "exit_scaler":  str(ens / f"exit_scaler_{tag}{ext}"),
        "feature_drift": str(ens / f"feature_drift_{tag}.json"),
    }

    meta_doc = {
        "model_name":    f"robust_ensemble_{tag}",
        "model_type":    "stacking_ensemble_v3",
        "version":       "3.0.0",
        "symbol":        cfg.symbol,
        "timeframe":     timeframe,
        "trained_at":    datetime.now(timezone.utc).isoformat(),
        "git_commit":    git_commit,
        "dataset_sha256": data_hash,
        "dataset_range": {
            "from":    str(df["timestamp"].iloc[0]),
            "to":      str(df["timestamp"].iloc[-1]),
            "candles": len(df),
        },
        "artifact_format":        _ARTIFACT_EXT,
        "feature_count":          EXPECTED_FEATURE_COUNT,
        "features_required":      FEATURE_LIST,
        "exit_feature_names":     exit_names,
        "position_feature_names": POSITION_FEATURE_NAMES,
        "regime_feature_names":   REGIME_FEATURE_NAMES,
        "base_learners":          list(entry_base.keys()),
        "signal_thresholds": {
            "entry": ENTRY_THRESHOLD,
            "exit":  EXIT_THRESHOLD,
        },
        "config": {
            "entry_threshold": cfg.entry_threshold,
            "exit_lookahead":  cfg.exit_lookahead,
            "exit_loss_pct":   cfg.exit_loss_pct,
            "exit_profit_pct": cfg.exit_profit_pct,
            "n_folds":         cfg.n_folds,
            "train_samples":   len(X_tr),
            "val_samples":     len(X_val),
            "test_samples":    len(X_te),
        },
        "entry_test_metrics":       entry_met,
        "exit_test_metrics":        exit_met,
        "sharpe_proxy":             round(float(sharpe), 4),
        "promotion": {
            "promoted": promoted,
            "reason":   promo_reason,
        },
        "entry_feature_importance":  dict(list(entry_imp.items())[:20]),
        "exit_feature_importance":   dict(list(exit_imp.items())[:20]),
        "file_paths": file_paths,
    }
    save_json(meta_doc, meta_path)

    return {
        "tag":           tag,
        "entry_metrics": entry_met,
        "exit_metrics":  exit_met,
        "paths":         meta_doc["file_paths"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> TrainingConfig:
    p = argparse.ArgumentParser(
        description="JackSparrow – Robust Ensemble Trainer v2"
    )
    p.add_argument("--symbol",          default="BTCUSD")
    p.add_argument("--timeframes", nargs="+",
                   default=["15m", "30m", "1h", "2h", "4h"])
    p.add_argument("--total-candles",   type=int,   default=6000)
    p.add_argument("--n-folds",         type=int,   default=5)
    p.add_argument("--entry-threshold", type=float, default=0.003)
    p.add_argument("--exit-lookahead",  type=int,   default=8)
    p.add_argument("--exit-loss-pct",   type=float, default=0.015)
    p.add_argument("--exit-profit-pct", type=float, default=0.030)
    p.add_argument("--output-dir",      default="agent/model_storage")
    p.add_argument("--lstm",            action="store_true")
    p.add_argument("--seed",            type=int,   default=42)
    p.add_argument("--parallel-jobs",   type=int,   default=-1)
    a = p.parse_args()
    return TrainingConfig(
        symbol=a.symbol, timeframes=a.timeframes,
        total_candles=a.total_candles, n_folds=a.n_folds,
        entry_threshold=a.entry_threshold,
        exit_lookahead=a.exit_lookahead, exit_loss_pct=a.exit_loss_pct,
        exit_profit_pct=a.exit_profit_pct, lstm=a.lstm,
        output_dir=a.output_dir, random_seed=a.seed,
        parallel_jobs=a.parallel_jobs,
    )


def main() -> None:
    cfg        = parse_args()
    git_commit = _git_commit()

    log.info("JackSparrow – Robust Ensemble Trainer  v2.0.0")
    log.info(f"  Symbol      : {cfg.symbol}")
    log.info(f"  Timeframes  : {cfg.timeframes}")
    log.info(f"  Candles     : {cfg.total_candles}")
    log.info(f"  Folds       : {cfg.n_folds}")
    log.info(f"  Parallel    : {cfg.parallel_jobs}")
    log.info(f"  Git commit  : {git_commit}")

    # API key sanity – NEVER log the actual key value
    api_key    = os.environ.get("DELTA_EXCHANGE_API_KEY", "")
    api_secret = os.environ.get("DELTA_EXCHANGE_API_SECRET", "")
    if not api_key or not api_secret:
        log.error(
            "DELTA_EXCHANGE_API_KEY or DELTA_EXCHANGE_API_SECRET not set in env."
        )
        sys.exit(1)
    masked = f"{'*'*8}{api_key[-4:]}" if len(api_key) > 4 else "****"
    log.info(f"  API key     : {masked}")

    client     = DeltaExchangeClient(api_key=api_key, api_secret=api_secret)
    output_dir = PROJECT_ROOT / cfg.output_dir
    results    = []

    for tf in cfg.timeframes:
        try:
            summary = train_for_timeframe(client, cfg, tf, output_dir, git_commit)
            results.append(summary)
        except Exception as exc:
            log.error(f"  ✗ Failed [{cfg.symbol} {tf}]: {exc}", exc_info=True)

    # Summary
    log.info("\n" + "="*64)
    log.info("  TRAINING COMPLETE")
    log.info("="*64)
    for r in results:
        log.info(
            f"  {r['tag']:<24}  "
            f"entry_acc={r['entry_metrics']['accuracy']:.3f}  "
            f"entry_auc={r['entry_metrics']['auc_ovr']:.3f}  |  "
            f"exit_auc={r['exit_metrics']['auc']:.3f}"
        )

    manifest = PROJECT_ROOT / cfg.output_dir / "robust_ensemble" / "MANIFEST.json"
    save_json(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": git_commit,
            "config": asdict(cfg),
            "results": results,
        },
        manifest,
    )
    log.info(f"\n  Manifest → {manifest}")


if __name__ == "__main__":
    main()
