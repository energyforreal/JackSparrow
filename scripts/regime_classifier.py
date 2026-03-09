"""
regime_classifier.py  (v3 – NEW)
----------------------------------
JackSparrow – Market Regime Classifier

Adds a two-stage regime-aware architecture on top of the existing stacking
ensemble.  Market regimes are detected FIRST; then a regime-specific entry
model is selected for prediction.

Architecture
------------
    Features
        ↓
    REGIME CLASSIFIER  →  TREND | RANGE | HIGH_VOL
        ↓
    ┌──────────┬──────────┬──────────┐
    Trend     Range    Volatile
    Model     Model     Model
    └──────────┴──────────┴──────────┘
        ↓
    Entry Signal
        ↓
    Exit Model

Regime Types
------------
    0 = RANGE      – low ADX, normal volatility → mean-reversion signals
    1 = TREND      – high ADX                  → momentum signals
    2 = HIGH_VOL   – high ATR percentile       → breakout signals

Timeframe Weight Adaptation
---------------------------
    TREND    → favour higher timeframes  (4h/2h dominant)
    RANGE    → balance toward lower TFs  (15m/30m boosted)
    HIGH_VOL → balance toward lower TFs  (fast reaction needed)

Artefacts
---------
    models/regime_model_{TAG}.joblib
    models/entry_trend_{TAG}.joblib
    models/entry_range_{TAG}.joblib
    models/entry_vol_{TAG}.joblib
    models/regime_metadata_{TAG}.json

Usage
-----
    # Training
    trainer = RegimeModelTrainer(cfg)
    trainer.train(feat_df, close, tag, output_dir)

    # Inference
    classifier = RegimeClassifier.from_metadata(path)
    regime = classifier.predict_regime(features)
    entry_signal = classifier.predict_entry(features, regime)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import joblib
    def _save(obj, p): joblib.dump(obj, p)
    def _load(p):      return joblib.load(p)
except ImportError:
    import pickle
    def _save(obj, p):
        with open(p, "wb") as f: pickle.dump(obj, f, protocol=4)
    def _load(p):
        with open(p, "rb") as f: return pickle.load(f)

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, f1_score
from sklearn.preprocessing import RobustScaler

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Regime constants
# ─────────────────────────────────────────────────────────────────────────────

REGIME_RANGE    = 0
REGIME_TREND    = 1
REGIME_HIGH_VOL = 2

REGIME_NAMES = {
    REGIME_RANGE:    "RANGE",
    REGIME_TREND:    "TREND",
    REGIME_HIGH_VOL: "HIGH_VOL",
}

# Timeframe weights per regime  (normalised to 1.0 by bridge)
REGIME_TF_WEIGHTS: Dict[int, Dict[str, float]] = {
    REGIME_TREND: {
        "4h": 0.40, "2h": 0.30, "1h": 0.20, "30m": 0.07, "15m": 0.03,
    },
    REGIME_RANGE: {
        "4h": 0.10, "2h": 0.15, "1h": 0.20, "30m": 0.25, "15m": 0.30,
    },
    REGIME_HIGH_VOL: {
        "4h": 0.15, "2h": 0.20, "1h": 0.25, "30m": 0.25, "15m": 0.15,
    },
}

# Feature names used exclusively by the regime model
REGIME_INPUT_FEATURES = [
    "adx_14",
    "atr_14",
    "bb_width",
    "volatility_zscore",
    "rsi_std",
    "price_slope",
    "volume_zscore",
]


# ─────────────────────────────────────────────────────────────────────────────
# Regime label generation
# ─────────────────────────────────────────────────────────────────────────────

def make_regime_labels(
    feat_df: pd.DataFrame,
    adx_trend_threshold: float = 25.0,
    atr_vol_percentile: float  = 80.0,
) -> pd.Series:
    """Generate heuristic regime labels from market-structure features.

    Labelling rules (applied in order):
        1. HIGH_VOL  if ATR percentile-rank > atr_vol_percentile
        2. TREND     if ADX > adx_trend_threshold
        3. RANGE     otherwise

    This heuristic produces clean training labels.  A refined labeller can
    be trained as a second-pass supervised model later.
    """
    n = len(feat_df)
    labels = np.full(n, REGIME_RANGE, dtype=int)

    # ADX
    adx_col = None
    for c in ("adx_14", "adx_14_regime", "adx"):
        if c in feat_df.columns:
            adx_col = feat_df[c].fillna(20.0).values
            break
    if adx_col is None:
        adx_col = np.full(n, 20.0)

    # ATR (normalised)
    atr_col = None
    for c in ("atr_14", "atr_pct_rank", "atr"):
        if c in feat_df.columns:
            atr_col = feat_df[c].fillna(0.5).values
            break
    if atr_col is None:
        atr_col = np.full(n, 0.5)

    # Compute rolling percentile of ATR
    atr_series = pd.Series(atr_col)
    atr_pct    = (
        atr_series.rolling(50, min_periods=5)
        .apply(lambda x: float(pd.Series(x).rank(pct=True).iloc[-1]), raw=False)
        .fillna(0.5)
        .values
    )

    trend_mask   = adx_col > adx_trend_threshold
    vol_mask     = atr_pct > (atr_vol_percentile / 100.0)

    labels[trend_mask]  = REGIME_TREND
    labels[vol_mask]    = REGIME_HIGH_VOL      # vol overrides trend

    counts = {REGIME_NAMES[r]: int((labels == r).sum()) for r in range(3)}
    log.info(f"  Regime label distribution: {counts}")
    return pd.Series(labels, index=feat_df.index, dtype=int)


# ─────────────────────────────────────────────────────────────────────────────
# Regime feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_regime_features(
    feat_df: pd.DataFrame,
    close: pd.Series,
) -> pd.DataFrame:
    """Extract the 7 regime-specific input features from the full feature matrix."""
    out = pd.DataFrame(index=feat_df.index)

    # 1. ADX-14
    for c in ("adx_14", "adx"):
        if c in feat_df.columns:
            out["adx_14"] = feat_df[c].fillna(20.0)
            break
    else:
        out["adx_14"] = 20.0

    # 2. ATR-14 normalised by price
    for c in ("atr_14", "atr"):
        if c in feat_df.columns:
            out["atr_14"] = (feat_df[c] / close.replace(0, np.nan)).fillna(0.0)
            break
    else:
        out["atr_14"] = 0.0

    # 3. Bollinger bandwidth
    for c in ("bb_width", "bollinger_width", "bb_bandwidth"):
        if c in feat_df.columns:
            out["bb_width"] = feat_df[c].fillna(0.0)
            break
    else:
        # Compute from close if not available
        sma20   = close.rolling(20, min_periods=5).mean()
        std20   = close.rolling(20, min_periods=5).std().fillna(1e-8)
        out["bb_width"] = (2.0 * std20 / sma20.replace(0, np.nan)).fillna(0.0)

    # 4. Volatility z-score (20-period vol vs 100-period baseline)
    log_ret  = np.log(close / close.shift(1)).fillna(0.0)
    vol_20   = log_ret.rolling(20, min_periods=5).std().fillna(0.0)
    vol_mean = vol_20.rolling(100, min_periods=10).mean().fillna(0.0)
    vol_std  = vol_20.rolling(100, min_periods=10).std().replace(0, np.nan).fillna(1e-8)
    out["volatility_zscore"] = ((vol_20 - vol_mean) / vol_std).clip(-3, 3).fillna(0.0)

    # 5. RSI rolling std (measures how much RSI oscillates)
    for c in ("rsi_14", "rsi"):
        if c in feat_df.columns:
            out["rsi_std"] = (
                feat_df[c].rolling(20, min_periods=5).std().fillna(10.0)
            )
            break
    else:
        out["rsi_std"] = 10.0

    # 6. Price slope (linear regression slope over 20 bars, normalised)
    log_close = np.log(close.replace(0, np.nan).ffill())
    slopes = []
    arr = log_close.values
    for i in range(len(arr)):
        start = max(0, i - 19)
        window = arr[start:i+1]
        if len(window) >= 2:
            x = np.arange(len(window), dtype=float)
            slope = np.polyfit(x, window, 1)[0]
        else:
            slope = 0.0
        slopes.append(slope)
    out["price_slope"] = slopes

    # 7. Volume z-score
    if "volume" in feat_df.columns:
        vol_s   = feat_df["volume"].replace(0, np.nan).ffill().fillna(1.0)
        vol_m   = vol_s.rolling(20, min_periods=5).mean().fillna(1.0)
        vol_std2 = vol_s.rolling(20, min_periods=5).std().replace(0, np.nan).fillna(1e-8)
        out["volume_zscore"] = ((vol_s - vol_m) / vol_std2).clip(-3, 3).fillna(0.0)
    else:
        out["volume_zscore"] = 0.0

    return out.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Regime model trainer
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RegimeTrainingConfig:
    n_folds:     int   = 5
    seed:        int   = 42
    n_jobs:      int   = -1
    train_split: float = 0.70
    val_split:   float = 0.15
    adx_trend_threshold: float = 25.0
    atr_vol_percentile:  float = 80.0


def _make_regime_classifier(seed: int) -> Any:
    if HAS_XGB:
        return xgb.XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", use_label_encoder=False,
            random_state=seed, n_jobs=1, verbosity=0,
        )
    return RandomForestClassifier(
        n_estimators=200, max_depth=8, min_samples_leaf=10,
        class_weight="balanced", random_state=seed, n_jobs=1,
    )


def _make_entry_model(seed: int) -> Any:
    """Regime-specific entry model (same architecture as base learner)."""
    if HAS_XGB:
        return xgb.XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
            gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", use_label_encoder=False,
            random_state=seed, n_jobs=1, verbosity=0,
        )
    return RandomForestClassifier(
        n_estimators=200, max_depth=10, min_samples_leaf=10,
        class_weight="balanced", random_state=seed, n_jobs=1,
    )


def _fit_model(
    model: Any,
    X_tr: np.ndarray, y_tr: np.ndarray,
    X_es: np.ndarray, y_es: np.ndarray,
) -> Any:
    if HAS_XGB and isinstance(model, xgb.XGBClassifier):
        model.fit(X_tr, y_tr, eval_set=[(X_es, y_es)], verbose=False)
    elif HAS_LGB and isinstance(model, lgb.LGBMClassifier):
        cbs = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(-1)]
        model.fit(X_tr, y_tr, eval_set=[(X_es, y_es)], callbacks=cbs)
    else:
        model.fit(X_tr, y_tr)
    return model


class RegimeModelTrainer:
    """Train regime classifier + 3 regime-specific entry models."""

    def __init__(self, cfg: RegimeTrainingConfig) -> None:
        self.cfg = cfg

    def train(
        self,
        feat_df:   pd.DataFrame,
        close:     pd.Series,
        entry_lbl: pd.Series,
        tag:       str,
        output_dir: Path,
    ) -> Dict[str, Any]:
        """Train all regime models and save artifacts.

        Returns a summary dict with metrics.
        """
        cfg = self.cfg
        log.info(f"\n{'='*60}")
        log.info(f"  Regime model training → {tag}")
        log.info(f"{'='*60}")

        # 1. Extract regime features
        reg_feat_df = extract_regime_features(feat_df, close)

        # 2. Generate regime labels
        regime_lbl = make_regime_labels(
            feat_df,
            adx_trend_threshold = cfg.adx_trend_threshold,
            atr_vol_percentile  = cfg.atr_vol_percentile,
        )

        n      = len(feat_df)
        tr_end = int(n * cfg.train_split)
        va_end = int(n * (cfg.train_split + cfg.val_split))

        X_reg    = reg_feat_df.values.astype(np.float32)
        X_entry  = feat_df.values.astype(np.float32)
        y_regime = regime_lbl.values
        y_entry  = entry_lbl.values

        # Splits
        Xr_tr, Xr_va, Xr_te = X_reg[:tr_end],    X_reg[tr_end:va_end],   X_reg[va_end:]
        Xe_tr, Xe_va, Xe_te = X_entry[:tr_end],   X_entry[tr_end:va_end], X_entry[va_end:]
        yr_tr, yr_va, yr_te = y_regime[:tr_end],   y_regime[tr_end:va_end], y_regime[va_end:]
        ye_tr, ye_va, ye_te = y_entry[:tr_end],    y_entry[tr_end:va_end],  y_entry[va_end:]

        # Scalers
        reg_scaler   = RobustScaler().fit(Xr_tr)
        entry_scaler = RobustScaler().fit(Xe_tr)
        Xr_tr_s = reg_scaler.transform(Xr_tr)
        Xr_te_s = reg_scaler.transform(Xr_te)
        Xe_tr_s = entry_scaler.transform(Xe_tr)

        # 3. Train regime classifier (walk-forward)
        log.info("  Training regime classifier (walk-forward) …")
        regime_model = _make_regime_classifier(cfg.seed)
        tscv = TimeSeriesSplit(n_splits=cfg.n_folds)
        for fold, (tri, vai) in enumerate(tscv.split(Xr_tr_s)):
            es = max(1, len(tri) // 10)
            _fit_model(
                regime_model,
                Xr_tr_s[tri[:-es]], yr_tr[tri[:-es]],
                Xr_tr_s[tri[-es:]], yr_tr[tri[-es:]],
            )
            log.info(f"    Fold {fold+1}/{cfg.n_folds} done")

        # Re-fit on full train set
        es_sz = max(1, len(Xr_tr_s) // 10)
        regime_model = _make_regime_classifier(cfg.seed)
        _fit_model(
            regime_model,
            Xr_tr_s[:-es_sz], yr_tr[:-es_sz],
            Xr_tr_s[-es_sz:], yr_tr[-es_sz:],
        )

        regime_test_pred = regime_model.predict(Xr_te_s)
        regime_acc = accuracy_score(yr_te, regime_test_pred)
        regime_f1  = f1_score(yr_te, regime_test_pred, average="macro", zero_division=0)
        log.info(f"  Regime classifier  acc={regime_acc:.4f}  f1={regime_f1:.4f}")

        # 4. Train regime-specific entry models
        entry_models: Dict[int, Any] = {}
        entry_metrics: Dict[str, Dict] = {}

        for regime_id, regime_name in REGIME_NAMES.items():
            mask_tr = yr_tr == regime_id
            mask_te = yr_te == regime_id

            n_train = mask_tr.sum()
            log.info(
                f"  Training entry model [{regime_name}] "
                f"n_train={n_train} …"
            )
            if n_train < 50:
                log.warning(
                    f"  Insufficient samples for {regime_name} "
                    f"({n_train} < 50) – using global model fallback."
                )
                entry_models[regime_id] = None
                continue

            X_regime = Xe_tr_s[mask_tr]
            y_regime_entry = ye_tr[mask_tr]

            model = _make_entry_model(cfg.seed + regime_id)
            es_sz2 = max(1, len(X_regime) // 10)
            _fit_model(
                model,
                X_regime[:-es_sz2], y_regime_entry[:-es_sz2],
                X_regime[-es_sz2:], y_regime_entry[-es_sz2:],
            )
            entry_models[regime_id] = model

            if mask_te.sum() > 0:
                X_te_r = entry_scaler.transform(Xe_te[mask_te])
                y_te_r = ye_te[mask_te]
                preds = model.predict(X_te_r)
                m_acc = accuracy_score(y_te_r, preds)
                m_f1  = f1_score(y_te_r, preds, average="macro", zero_division=0)
                entry_metrics[regime_name] = {"accuracy": round(m_acc, 4), "f1": round(m_f1, 4)}
                log.info(f"  {regime_name} entry  acc={m_acc:.4f}  f1={m_f1:.4f}")

        # 5. Save artifacts
        output_dir.mkdir(parents=True, exist_ok=True)

        _save(regime_model,   output_dir / f"regime_model_{tag}.joblib")
        _save(reg_scaler,     output_dir / f"regime_scaler_{tag}.joblib")
        _save(entry_scaler,   output_dir / f"entry_regime_scaler_{tag}.joblib")

        for regime_id, model in entry_models.items():
            if model is not None:
                name = REGIME_NAMES[regime_id].lower()
                _save(model, output_dir / f"entry_{name}_{tag}.joblib")
                log.info(f"  Saved entry_{name}_{tag}.joblib")

        # Save metadata
        meta = {
            "tag":             tag,
            "model_type":      "regime_classifier_v3",
            "version":         "3.0.0",
            "trained_at":      datetime.now(timezone.utc).isoformat(),
            "regime_names":    REGIME_NAMES,
            "regime_tf_weights": {
                str(k): v for k, v in REGIME_TF_WEIGHTS.items()
            },
            "config": {
                "adx_trend_threshold": cfg.adx_trend_threshold,
                "atr_vol_percentile":  cfg.atr_vol_percentile,
                "n_folds":             cfg.n_folds,
                "train_samples":       int(tr_end),
            },
            "regime_classifier_metrics": {
                "accuracy": round(float(regime_acc), 4),
                "f1_macro": round(float(regime_f1), 4),
            },
            "entry_model_metrics": entry_metrics,
            "file_paths": {
                "regime_model":          str(output_dir / f"regime_model_{tag}.joblib"),
                "regime_scaler":         str(output_dir / f"regime_scaler_{tag}.joblib"),
                "entry_regime_scaler":   str(output_dir / f"entry_regime_scaler_{tag}.joblib"),
                **{
                    f"entry_{REGIME_NAMES[r].lower()}": str(
                        output_dir / f"entry_{REGIME_NAMES[r].lower()}_{tag}.joblib"
                    )
                    for r in REGIME_NAMES
                },
            },
        }
        meta_path = output_dir / f"regime_metadata_{tag}.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)
        log.info(f"  Saved regime_metadata_{tag}.json")

        return meta


# ─────────────────────────────────────────────────────────────────────────────
# Runtime classifier (used by RobustEnsembleNode and EnsembleSignalBridge)
# ─────────────────────────────────────────────────────────────────────────────

class RegimeClassifier:
    """Load trained regime models and route predictions at inference time.

    Usage
    -----
        classifier = RegimeClassifier.from_metadata("models/regime_metadata_BTCUSD_1h.json")

        # Step 1: detect regime from regime features (7 values)
        regime_id = classifier.predict_regime(regime_features)
        regime_name = REGIME_NAMES[regime_id]  # "TREND" | "RANGE" | "HIGH_VOL"

        # Step 2: predict entry using regime-specific model
        proba = classifier.predict_entry(entry_features, regime_id)
        # proba shape: (3,)  [sell, hold, buy]

        # Step 3: get dynamic timeframe weights for this regime
        weights = classifier.get_tf_weights(regime_id)
    """

    _cache: Dict[str, "RegimeClassifier"] = {}

    def __init__(
        self,
        regime_model:        Any,
        regime_scaler:       Any,
        entry_scaler:        Any,
        entry_models:        Dict[int, Optional[Any]],
        metadata:            Dict[str, Any],
    ) -> None:
        self._regime_model  = regime_model
        self._regime_scaler = regime_scaler
        self._entry_scaler  = entry_scaler
        self._entry_models  = entry_models
        self._metadata      = metadata
        log.info(
            f"RegimeClassifier ready: {metadata.get('tag')}  "
            f"regimes={list(REGIME_NAMES.values())}"
        )

    @classmethod
    def from_metadata(cls, metadata_path: str | Path) -> "RegimeClassifier":
        """Load from metadata JSON.  Cached – safe to call repeatedly."""
        metadata_path = Path(metadata_path)
        key = str(metadata_path)
        if key in cls._cache:
            return cls._cache[key]

        with open(metadata_path) as f:
            meta = json.load(f)

        paths    = meta.get("file_paths", {})
        base_dir = metadata_path.parent

        def _p(key: str) -> Path:
            v = paths.get(key, "")
            p = Path(v)
            return p if p.is_absolute() else base_dir / p.name

        regime_model  = _load(_p("regime_model"))
        regime_scaler = _load(_p("regime_scaler"))
        entry_scaler  = _load(_p("entry_regime_scaler"))

        entry_models: Dict[int, Optional[Any]] = {}
        for regime_id, regime_name in REGIME_NAMES.items():
            key_name = f"entry_{regime_name.lower()}"
            try:
                entry_models[regime_id] = _load(_p(key_name))
                log.info(f"  Loaded entry model [{regime_name}]")
            except (FileNotFoundError, KeyError):
                log.warning(f"  No entry model for [{regime_name}] – will use fallback")
                entry_models[regime_id] = None

        inst = cls(
            regime_model  = regime_model,
            regime_scaler = regime_scaler,
            entry_scaler  = entry_scaler,
            entry_models  = entry_models,
            metadata      = meta,
        )
        cls._cache[key] = inst
        return inst

    def predict_regime(self, regime_features: List[float]) -> int:
        """Predict market regime from the 7 regime input features.

        Returns one of: REGIME_RANGE (0), REGIME_TREND (1), REGIME_HIGH_VOL (2)
        """
        X = np.array([regime_features], dtype=np.float32)
        X_s = self._regime_scaler.transform(X)
        regime = int(self._regime_model.predict(X_s)[0])
        return regime

    def predict_regime_proba(self, regime_features: List[float]) -> np.ndarray:
        """Predict regime probabilities → shape (3,)."""
        X   = np.array([regime_features], dtype=np.float32)
        X_s = self._regime_scaler.transform(X)
        return self._regime_model.predict_proba(X_s)[0]

    def predict_entry(
        self,
        entry_features: List[float],
        regime_id: int,
        fallback_regime_id: Optional[int] = None,
    ) -> np.ndarray:
        """Predict entry signal probabilities using regime-specific model.

        Falls back to the RANGE model if the regime-specific model is absent,
        then to any available model.

        Returns shape (3,): [P(SELL), P(HOLD), P(BUY)]
        """
        X   = np.array([entry_features], dtype=np.float32)
        X_s = self._entry_scaler.transform(X)

        # Try regime-specific model first
        model = self._entry_models.get(regime_id)
        if model is None:
            # Fallback chain: requested fallback → RANGE → any available
            fallback_order = [
                fallback_regime_id,
                REGIME_RANGE,
                REGIME_TREND,
                REGIME_HIGH_VOL,
            ]
            for fb in fallback_order:
                if fb is not None:
                    model = self._entry_models.get(fb)
                    if model is not None:
                        log.debug(
                            f"Regime {REGIME_NAMES[regime_id]} model missing, "
                            f"using {REGIME_NAMES[fb]} fallback."
                        )
                        break

        if model is None:
            log.warning("No entry model available – returning neutral proba.")
            return np.array([1/3, 1/3, 1/3], dtype=np.float32)

        return model.predict_proba(X_s)[0]

    def get_tf_weights(self, regime_id: int) -> Dict[str, float]:
        """Return timeframe weights appropriate for the given regime."""
        return REGIME_TF_WEIGHTS.get(regime_id, REGIME_TF_WEIGHTS[REGIME_RANGE])

    def get_regime_name(self, regime_id: int) -> str:
        return REGIME_NAMES.get(regime_id, "UNKNOWN")


# ─────────────────────────────────────────────────────────────────────────────
# Feature drift detection helper
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FeatureDriftStats:
    """Distribution statistics for a single feature, saved at training time.

    At inference time, compare live values against these baselines to detect
    feature drift before it silently degrades model performance.
    """
    feature_name: str
    mean:         float
    std:          float
    p10:          float
    p25:          float
    p50:          float
    p75:          float
    p90:          float
    n_samples:    int

    def zscore(self, value: float) -> float:
        """How many standard deviations is `value` from the training mean?"""
        if self.std < 1e-12:
            return 0.0
        return (value - self.mean) / self.std

    def is_drifted(self, value: float, threshold_sigma: float = 4.0) -> bool:
        return abs(self.zscore(value)) > threshold_sigma


def compute_feature_drift_stats(
    feat_df: pd.DataFrame,
    feature_names: List[str],
) -> List[FeatureDriftStats]:
    """Compute training-time distribution statistics for all features."""
    stats = []
    for name in feature_names:
        if name not in feat_df.columns:
            continue
        col = feat_df[name].dropna()
        if len(col) == 0:
            continue
        stats.append(FeatureDriftStats(
            feature_name = name,
            mean         = float(col.mean()),
            std          = float(col.std()),
            p10          = float(col.quantile(0.10)),
            p25          = float(col.quantile(0.25)),
            p50          = float(col.quantile(0.50)),
            p75          = float(col.quantile(0.75)),
            p90          = float(col.quantile(0.90)),
            n_samples    = int(len(col)),
        ))
    return stats


def drift_stats_to_dict(stats: List[FeatureDriftStats]) -> Dict[str, Dict]:
    return {
        s.feature_name: {
            "mean": s.mean, "std": s.std,
            "p10": s.p10, "p25": s.p25, "p50": s.p50,
            "p75": s.p75, "p90": s.p90,
            "n_samples": s.n_samples,
        }
        for s in stats
    }


def check_live_drift(
    features: List[float],
    feature_names: List[str],
    drift_dict: Dict[str, Dict],
    threshold_sigma: float = 4.0,
) -> List[str]:
    """Return names of features that exceed the drift threshold."""
    drifted = []
    for name, val in zip(feature_names, features):
        stat = drift_dict.get(name)
        if stat is None:
            continue
        std = stat.get("std", 0.0)
        mean = stat.get("mean", 0.0)
        if std < 1e-12:
            continue
        if abs((val - mean) / std) > threshold_sigma:
            drifted.append(name)
    return drifted


# ─────────────────────────────────────────────────────────────────────────────
# Model promotion gate
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelPromotionResult:
    promoted:       bool
    new_score:      float
    baseline_score: float
    reason:         str


def evaluate_sharpe_proxy(
    proba: np.ndarray,
    y_true: np.ndarray,
    close: np.ndarray,
    lookahead: int = 1,
) -> float:
    """Compute a simplified Sharpe proxy from predicted signals vs returns.

    Signal: +1 = BUY, 0 = HOLD, -1 = SELL  (from argmax of 3-class proba)
    Return: forward log return over `lookahead` bars
    """
    pred_class = np.argmax(proba, axis=1)   # 0=SELL, 1=HOLD, 2=BUY
    signal = np.where(pred_class == 2, 1.0,
             np.where(pred_class == 0, -1.0, 0.0))

    n = min(len(signal), len(close) - lookahead)
    if n < 10:
        return 0.0

    fwd_ret = np.log(close[lookahead:n+lookahead] / close[:n])
    strategy_ret = signal[:n] * fwd_ret
    if strategy_ret.std() < 1e-10:
        return 0.0
    return float(strategy_ret.mean() / strategy_ret.std() * np.sqrt(252))


def should_promote_model(
    new_score: float,
    baseline_path: Optional[Path],
    min_improvement: float = 0.05,
) -> ModelPromotionResult:
    """Gate model promotion behind a Sharpe improvement check.

    If no baseline exists the new model is always promoted.
    The new model must exceed baseline by at least `min_improvement`.
    """
    if baseline_path is None or not Path(str(baseline_path)).exists():
        return ModelPromotionResult(
            promoted       = True,
            new_score      = new_score,
            baseline_score = 0.0,
            reason         = "No baseline exists – promoting automatically.",
        )

    try:
        with open(baseline_path) as f:
            baseline_meta = json.load(f)
        baseline_score = float(
            baseline_meta.get("sharpe_proxy", 0.0)
        )
    except Exception:
        baseline_score = 0.0

    if new_score >= baseline_score + min_improvement:
        return ModelPromotionResult(
            promoted       = True,
            new_score      = new_score,
            baseline_score = baseline_score,
            reason         = (
                f"New Sharpe proxy {new_score:.4f} exceeds "
                f"baseline {baseline_score:.4f} by "
                f"{new_score - baseline_score:.4f} ≥ {min_improvement}."
            ),
        )
    return ModelPromotionResult(
        promoted       = False,
        new_score      = new_score,
        baseline_score = baseline_score,
        reason         = (
            f"New Sharpe proxy {new_score:.4f} does NOT exceed "
            f"baseline {baseline_score:.4f} + margin {min_improvement}. "
            "Live model unchanged."
        ),
    )
