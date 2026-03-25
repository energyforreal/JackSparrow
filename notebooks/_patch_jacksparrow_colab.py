"""One-shot patch: align JackSparrow_Trading_Colab_v4.ipynb with MTF runtime."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_PATH = ROOT / "notebooks" / "JackSparrow_Trading_Colab_v4.ipynb"


def main() -> None:
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))

    def set_md(idx: int, text: str) -> None:
        nb["cells"][idx]["cell_type"] = "markdown"
        nb["cells"][idx]["source"] = [text + "\n"] if not text.endswith("\n\n") else [text]

    def set_code(idx: int, text: str) -> None:
        nb["cells"][idx]["cell_type"] = "code"
        nb["cells"][idx]["source"] = [text]
        if "outputs" in nb["cells"][idx]:
            nb["cells"][idx]["outputs"] = []

    # --- Cell 0 ---
    set_md(
        0,
        """# JackSparrow Trading Agent — Colab Training Lab (v5)

**MTF-aligned stack (matches live agent defaults):** timeframes **`3m`, `5m`, `15m` only** — **no 1m** (noise / Sharpe drag). Runtime roles: **15m trend** and **5m entry** with probability-gated MTF decisions; **3m is optional filter only** when explicitly enabled.

**Expanded ~127 features** (canonical + candlestick + chart patterns + **MTF context** on **5m primary**), **fee-aware TP/SL entry labeling** aligned with execution: **TP = 0.6%**, **SL = 0.4%** (see `TP_PCT` / `SL_PCT` below).

**Live exits:** the agent uses **rule-based exits** (TP/SL, trailing, max hold) with `USE_ML_EXIT_MODEL=false`. This notebook trains **entry (long + short) models only** — no exit classifier export (smaller ZIP, no imbalanced exit F1). Execution-side SR/BB filters are applied in the trading handler, not in notebook training.

**Trade-level check:** after export, optionally run the repo script `scripts/trade_simulator.py` on OHLCV CSV for PnL / drawdown sanity (separate from sklearn metrics).

> Note: filename stays `JackSparrow_Trading_Colab_v4.ipynb` for compatibility.

### Pipeline
```
Delta Exchange API  →  Candle Fetch  →  Feature Engineering
→  Label Generation  →  Train (Entry long + short per TF)
→  Walk-Forward Validation  →  Export ZIP  →  Download
```

| Section | Description |
|---------|-------------|
| 0 | Environment setup & imports |
| 1 | Configuration |
| 2 | Candle download |
| 3 | Feature engineering |
| 4 | Label generation |
| 5 | Model training |
| 6 | Walk-forward validation |
| 7 | Export & download |
""",
    )

    # --- Cell 5: imports ---
    set_code(
        5,
        r"""import warnings, json, hashlib, time, threading, shutil, subprocess, random
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from tqdm.auto import tqdm

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import RobustScaler
from sklearn.calibration import CalibratedClassifierCV

import xgboost as xgb
import lightgbm as lgb

from feature_store.unified_feature_engine import UnifiedFeatureEngine
from feature_store.feature_registry import EXPANDED_FEATURE_LIST

# Reproducibility: deterministic seeds for notebook pipeline.
np.random.seed(42)
random.seed(42)

warnings.filterwarnings('ignore')
print('✅ Imports OK (UnifiedFeatureEngine + EXPANDED_FEATURE_LIST). Seeds fixed: 42.')
""",
    )

    # --- Cell 8: Config ---
    set_code(
        8,
        r"""# ── 1.2  Main configuration ───────────────────────────────────────────────────
@dataclass
class Config:
    symbol:            str   = 'BTCUSD'
    timeframes:        list  = field(default_factory=lambda: ['5m', '15m'])
    total_candles:     int   = 10_000   # fallback if a TF is missing from CANDLE_TARGET
    n_folds:           int   = 5
    train_split:       float = 0.70
    val_split:         float = 0.15     # remaining 15 % = test
    random_seed:       int   = 42
    n_jobs:            int   = -1
    top_n_features:    int   = 20       # use top-N features by variance

    # Adaptive lookahead (candles ahead for entry / TP-SL label window).
    # Option A: longer window → more TP-before-SL positives at same TP/SL as agent.
    entry_lookahead_map: dict = field(default_factory=lambda: {
        '5m': 20,
        '15m': 10,
    })

    label_mode: str = 'tp_sl'
    hybrid_return_threshold: float = 0.003
    use_calibration: bool = True


# Per-timeframe history length (pagination uses ~2000-bar time windows via start/end).
CANDLE_TARGET = {
    '5m': 12_000,
    '15m': 10_000,
}

CFG = Config()
print('Configuration:')
for k, v in asdict(CFG).items():
    print(f'  {k:<25} = {v}')
print('  CANDLE_TARGET             =', CANDLE_TARGET)
""",
    )

    # --- Cell 19: TP/SL defaults in labeling helpers ---
    cell19 = "".join(nb["cells"][19]["source"])
    cell19 = cell19.replace("tp_pct: float = 0.0030,", "tp_pct: float = 0.0060,")
    cell19 = cell19.replace("sl_pct: float = 0.0020,", "sl_pct: float = 0.0040,")
    cell19 = cell19.replace("tp_pct: float = 0.0020,", "tp_pct: float = 0.0060,")
    cell19 = cell19.replace("sl_pct: float = 0.0015,", "sl_pct: float = 0.0040,")
    nb["cells"][19]["source"] = [cell19]
    if "outputs" in nb["cells"][19]:
        nb["cells"][19]["outputs"] = []

    # --- Cell 22: drop exit label helper ---
    set_code(
        22,
        r"""# ── 4.1  Entry targets: binary LONG / SHORT ───────────────────────────────────
def make_entry_labels(close: pd.Series, lookahead: int = 1,
                      threshold: float = 0.006) -> pd.Series:
    # Legacy helper (not used for primary training path — TP/SL labels below are authoritative).
    fwd = close.shift(-max(lookahead, 1)) / close - 1.0
    lbl = np.where(fwd > threshold, 2,
          np.where(fwd < -threshold, 0, 1))
    return pd.Series(lbl, index=close.index, dtype=int)


# Live agent exits are TP/SL + trailing + time (no ML exit model). No exit labels trained here.


def hybrid_forward_return_labels(
    close: pd.Series,
    horizon_bars: int,
    threshold: float,
) -> Tuple[pd.Series, pd.Series]:
    """Binary long/short from signed forward return at horizon (JackSparrow v6 option)."""
    h = max(1, int(horizon_bars))
    future = close.shift(-h)
    ret = (future - close) / close
    long_y = (ret > threshold).astype(int)
    short_y = (ret < -threshold).astype(int)
    return long_y, short_y


print('✅ Label functions defined (TP/SL primary; hybrid forward-return helper for v6).')
""",
    )

    # --- Cell 23: labels loop ---
    set_code(
        23,
        r"""# ── 4.3  Generate labels for all timeframes ───────────────────────────────────
# Entry: binary LONG/SHORT targets derived from TP/SL outcomes (fee-aware).
ENTRY_LONG_LABELS: Dict[str, pd.Series] = {}
ENTRY_SHORT_LABELS: Dict[str, pd.Series] = {}

# Align with agent defaults: 0.6% TP, 0.4% SL (fraction of price). Tune FEE_PCT to your tier.
TP_PCT, SL_PCT, FEE_PCT = 0.0060, 0.0040, 0.0005
ENTRY_MAX_BARS: Dict[str, int] = {}

for tf in CFG.timeframes:
    prices_df = PRICES[tf].reset_index(drop=True)
    n_use = len(FEATS[tf])

    max_bars = int(CFG.entry_lookahead_map.get(tf, 6))
    ENTRY_MAX_BARS[tf] = max_bars

    close_v = prices_df['close'].iloc[:n_use]

    if getattr(CFG, 'label_mode', 'tp_sl').lower() == 'hybrid':
        hz = max_bars
        y_long_raw, y_short_raw = hybrid_forward_return_labels(
            close_v.reset_index(drop=True),
            hz,
            float(getattr(CFG, 'hybrid_return_threshold', 0.003)),
        )
        safe_n = n_use - hz
        ENTRY_LONG_LABELS[tf] = y_long_raw.iloc[:safe_n].reset_index(drop=True)
        ENTRY_SHORT_LABELS[tf] = y_short_raw.iloc[:safe_n].reset_index(drop=True)
        yl = ENTRY_LONG_LABELS[tf]
        ys = ENTRY_SHORT_LABELS[tf]
        overlap_ratio = float(((yl == 1) & (ys == 1)).mean())
        print(
            f'  [{tf}]  hybrid hz={hz}  thr={CFG.hybrid_return_threshold:.4f}  '
            f'samples={len(yl)}  LONG_POS={int(yl.sum())}  SHORT_POS={int(ys.sum())}  '
            f'overlap={overlap_ratio:.2%}'
        )
        continue

    # TP/SL entry labels (fee-aware, directional) -> binary long/short targets
    y_long, y_short = create_binary_entry_targets(
        prices_df.iloc[:n_use],
        tp_pct=TP_PCT,
        sl_pct=SL_PCT,
        max_bars=max_bars,
        fee_pct=FEE_PCT,
    )
    y_long = y_long.iloc[:n_use].reset_index(drop=True)
    y_short = y_short.iloc[:n_use].reset_index(drop=True)

    safe_n = n_use - max_bars
    ENTRY_LONG_LABELS[tf] = y_long.iloc[:safe_n].reset_index(drop=True)
    ENTRY_SHORT_LABELS[tf] = y_short.iloc[:safe_n].reset_index(drop=True)

    yl = ENTRY_LONG_LABELS[tf]
    ys = ENTRY_SHORT_LABELS[tf]
    overlap_ratio = float(((yl == 1) & (ys == 1)).mean())

    print(
        f'  [{tf}]  samples={len(yl)}  '
        f'LONG_POS={int(yl.sum())}  SHORT_POS={int(ys.sum())}  '
        f'overlap={overlap_ratio:.2%}  TP_SL={TP_PCT:.2%}/{SL_PCT:.2%}'
    )

print('\n✅ Labels generated (binary long/short entry only; exits = execution rules).')
""",
    )

    # --- Cell 24: charts ---
    set_code(
        24,
        r"""# ── 4.4  Label distribution chart ────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
tf_show = '5m' if '5m' in CFG.timeframes else CFG.timeframes[0]

# Entry long
lv = ENTRY_LONG_LABELS[tf_show].value_counts().sort_index()
axes[0].bar(['LONG=0','LONG=1'], [int(lv.get(0, 0)), int(lv.get(1, 0))],
            color=['#95a5a6','#2ecc71'])
axes[0].set_title(f'Entry Long Labels — {tf_show}')
axes[0].set_ylabel('Count')

# Entry short
sv = ENTRY_SHORT_LABELS[tf_show].value_counts().sort_index()
axes[1].bar(['SHORT=0','SHORT=1'], [int(sv.get(0, 0)), int(sv.get(1, 0))],
            color=['#95a5a6','#e74c3c'])
axes[1].set_title(f'Entry Short Labels — {tf_show}')

plt.suptitle(f'{CFG.symbol} Entry Label Distributions (TP/SL-derived)')
plt.tight_layout()
plt.savefig(REPORT_DIR / 'label_distributions.png', dpi=120, bbox_inches='tight')
plt.show()
print('✅ Chart saved.')
""",
    )

    # --- Cell 25 markdown ---
    set_md(
        25,
        """---
## 5 — Model Training

Two **entry models** per timeframe: binary **LONG** and binary **SHORT** XGBoost classifiers. **No exit model** (live agent uses TP/SL / trailing / time exits).
""",
    )

    # --- Cell 26: builders ---
    set_code(
        26,
        r"""# ── 5.1  Model builders ───────────────────────────────────────────────────────
def make_entry_model(seed: int, scale_pos_weight: float = 1.0) -> xgb.XGBClassifier:
    # Binary entry classifier used for LONG and SHORT targets.
    return xgb.XGBClassifier(
        n_estimators=300, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=10,
        gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
        objective='binary:logistic',
        eval_metric='aucpr',
        scale_pos_weight=scale_pos_weight,
        use_label_encoder=False,
        early_stopping_rounds=30,
        random_state=seed, n_jobs=1, verbosity=0,
    )


def _binary_scale_pos_weight(y: np.ndarray) -> float:
    return float((y == 0).sum()) / max(1, int((y == 1).sum()))


def _print_threshold_sweep(name: str, model: xgb.XGBClassifier, X_va: np.ndarray, y_va: np.ndarray) -> None:
    proba = model.predict_proba(X_va)[:, 1]
    print(f'  {name} validation threshold sweep (precision / recall / F1 pos):')
    for th in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        pred = (proba >= th).astype(int)
        p = precision_score(y_va, pred, pos_label=1, zero_division=0)
        r = recall_score(y_va, pred, pos_label=1, zero_division=0)
        f = f1_score(y_va, pred, pos_label=1, zero_division=0)
        print(f'    th={th:.2f}  precision={p:.4f}  recall={r:.4f}  f1_pos={f:.4f}')


print('✅ Model builders defined (entry only).')
""",
    )

    # --- Cell 27: training loop ---
    set_code(
        27,
        r"""# ── 5.2  Train entry models for every timeframe ────────────────────────────────
ENTRY_LONG_MODELS:   Dict[str, Any] = {}
ENTRY_SHORT_MODELS:  Dict[str, Any] = {}
ENTRY_LONG_SCALERS:  Dict[str, Any] = {}
ENTRY_SHORT_SCALERS: Dict[str, Any] = {}
TRAIN_METRICS:  Dict[str, Dict] = {}

for tf in CFG.timeframes:
    print(f'\n── [{tf}] ──────────────────────────────────────────────')

    top_feats = TOP_FEATURES[tf]
    n_safe    = len(ENTRY_LONG_LABELS[tf])
    X_all     = FEATS[tf][top_feats].iloc[:n_safe].values.astype(np.float32)
    y_long    = ENTRY_LONG_LABELS[tf].values
    y_short   = ENTRY_SHORT_LABELS[tf].values

    n      = len(X_all)
    tr_end = int(n * CFG.train_split)
    va_end = int(n * (CFG.train_split + CFG.val_split))

    X_tr, y_l_tr = X_all[:tr_end], y_long[:tr_end]
    X_va, y_l_va = X_all[tr_end:va_end], y_long[tr_end:va_end]
    X_te, y_l_te = X_all[va_end:], y_long[va_end:]
    y_s_tr = y_short[:tr_end]
    y_s_va = y_short[tr_end:va_end]
    y_s_te = y_short[va_end:]

    pos_long_tr = float(y_l_tr.mean())
    pos_short_tr = float(y_s_tr.mean())
    print(f'  Train positive rate  LONG={pos_long_tr:.2%}  SHORT={pos_short_tr:.2%}')
    if pos_long_tr < 0.08 or pos_short_tr < 0.08:
        print('  ⚠️  Low positive rate (<8%) — expect weak recall or unstable PR-AUC; consider more history or label tuning.')

    # ── Scale ───────────────────────────────────────────────────────────────
    l_scaler = RobustScaler().fit(X_tr)
    X_tr_s   = l_scaler.transform(X_tr)
    X_va_s   = l_scaler.transform(X_va)
    X_te_s   = l_scaler.transform(X_te)

    # ── Entry LONG model ────────────────────────────────────────────────────
    spw_l = _binary_scale_pos_weight(y_l_tr)
    l_model = make_entry_model(CFG.random_seed, scale_pos_weight=spw_l)
    l_model.fit(
        X_tr_s, y_l_tr,
        eval_set=[(X_va_s, y_l_va)],
        verbose=False
    )
    if getattr(CFG, 'use_calibration', False):
        cal_l = CalibratedClassifierCV(l_model, method='sigmoid', cv='prefit')
        cal_l.fit(X_va_s, y_l_va)
        l_model = cal_l
    y_l_pred = l_model.predict(X_te_s)
    l_acc    = accuracy_score(y_l_te, y_l_pred)
    l_f1     = f1_score(y_l_te, y_l_pred, zero_division=0)
    l_bacc   = balanced_accuracy_score(y_l_te, y_l_pred)
    l_ap     = average_precision_score(y_l_te, l_model.predict_proba(X_te_s)[:, 1])
    print(f'  Entry LONG  →  acc={l_acc:.4f}  bacc={l_bacc:.4f}  pr_auc={l_ap:.4f}  f1={l_f1:.4f}  (n_test={len(y_l_te)})')
    print('  Entry LONG classification report:')
    print(classification_report(y_l_te, y_l_pred, digits=4, zero_division=0))
    _print_threshold_sweep('Entry LONG', l_model, X_va_s, y_l_va)

    # ── Entry SHORT model ───────────────────────────────────────────────────
    s_scaler = RobustScaler().fit(X_tr)
    X_tr_ss  = s_scaler.transform(X_tr)
    X_va_ss  = s_scaler.transform(X_va)
    X_te_ss  = s_scaler.transform(X_te)
    spw_s = _binary_scale_pos_weight(y_s_tr)
    s_model = make_entry_model(CFG.random_seed + 1, scale_pos_weight=spw_s)
    s_model.fit(
        X_tr_ss, y_s_tr,
        eval_set=[(X_va_ss, y_s_va)],
        verbose=False
    )
    if getattr(CFG, 'use_calibration', False):
        cal_s = CalibratedClassifierCV(s_model, method='sigmoid', cv='prefit')
        cal_s.fit(X_va_ss, y_s_va)
        s_model = cal_s
    y_s_pred = s_model.predict(X_te_ss)
    s_acc    = accuracy_score(y_s_te, y_s_pred)
    s_f1     = f1_score(y_s_te, y_s_pred, zero_division=0)
    s_bacc   = balanced_accuracy_score(y_s_te, y_s_pred)
    s_ap     = average_precision_score(y_s_te, s_model.predict_proba(X_te_ss)[:, 1])
    print(f'  Entry SHORT →  acc={s_acc:.4f}  bacc={s_bacc:.4f}  pr_auc={s_ap:.4f}  f1={s_f1:.4f}  (n_test={len(y_s_te)})')
    print('  Entry SHORT classification report:')
    print(classification_report(y_s_te, y_s_pred, digits=4, zero_division=0))
    _print_threshold_sweep('Entry SHORT', s_model, X_va_ss, y_s_va)

    ENTRY_LONG_MODELS[tf]   = l_model
    ENTRY_SHORT_MODELS[tf]  = s_model
    ENTRY_LONG_SCALERS[tf]  = l_scaler
    ENTRY_SHORT_SCALERS[tf] = s_scaler

    TRAIN_METRICS[tf] = {
        'entry_long_acc': round(l_acc, 4),
        'entry_long_balanced_acc': round(l_bacc, 4),
        'entry_long_pr_auc': round(float(l_ap), 4),
        'entry_long_f1': round(l_f1, 4),
        'entry_short_acc': round(s_acc, 4),
        'entry_short_balanced_acc': round(s_bacc, 4),
        'entry_short_pr_auc': round(float(s_ap), 4),
        'entry_short_f1': round(s_f1, 4),
        'train_pos_rate_long': round(pos_long_tr, 4),
        'train_pos_rate_short': round(pos_short_tr, 4),
        'n_train': tr_end, 'n_test': len(y_l_te),
    }

print('\n✅ All entry models trained.')
""",
    )

    # --- Cell 30: walk-forward ---
    set_code(
        30,
        r"""# ── 6.1  TimeSeriesSplit walk-forward (long + short heads, combined-signal Sharpe) ──
WF_RESULTS: Dict[str, List[Dict]] = {}

for tf in CFG.timeframes:
    print(f'\n  [{tf}]  walk-forward ({CFG.n_folds} folds) …')

    top_feats = TOP_FEATURES[tf]
    n_safe    = len(ENTRY_LONG_LABELS[tf])
    X_all     = FEATS[tf][top_feats].iloc[:n_safe].values.astype(np.float32)
    y_long    = ENTRY_LONG_LABELS[tf].values
    y_short   = ENTRY_SHORT_LABELS[tf].values
    close_arr = PRICES[tf]['close'].iloc[:n_safe].values

    tscv   = TimeSeriesSplit(n_splits=CFG.n_folds)
    folds  = []

    for fold, (tri, tei) in enumerate(tscv.split(X_all)):
        X_tr, X_te = X_all[tri], X_all[tei]
        y_tr_l, y_te_l = y_long[tri], y_long[tei]
        y_tr_s, y_te_s = y_short[tri], y_short[tei]

        l_scaler = RobustScaler().fit(X_tr)
        X_tr_ls = l_scaler.transform(X_tr)
        X_te_ls = l_scaler.transform(X_te)

        s_scaler = RobustScaler().fit(X_tr)
        X_tr_ss = s_scaler.transform(X_tr)
        X_te_ss = s_scaler.transform(X_te)

        val_split = int(len(X_tr_ls) * 0.9)

        spw_l = float((y_tr_l == 0).sum()) / max(1, int((y_tr_l == 1).sum()))
        m_long = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            objective='binary:logistic',
            eval_metric='aucpr',
            scale_pos_weight=spw_l,
            use_label_encoder=False,
            early_stopping_rounds=30,
            random_state=CFG.random_seed, n_jobs=-1, verbosity=0
        )
        m_long.fit(
            X_tr_ls[:val_split], y_tr_l[:val_split],
            eval_set=[(X_tr_ls[val_split:], y_tr_l[val_split:])],
            verbose=False
        )

        spw_s = float((y_tr_s == 0).sum()) / max(1, int((y_tr_s == 1).sum()))
        m_short = xgb.XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            objective='binary:logistic',
            eval_metric='aucpr',
            scale_pos_weight=spw_s,
            use_label_encoder=False,
            early_stopping_rounds=30,
            random_state=CFG.random_seed + 1, n_jobs=-1, verbosity=0
        )
        m_short.fit(
            X_tr_ss[:val_split], y_tr_s[:val_split],
            eval_set=[(X_tr_ss[val_split:], y_tr_s[val_split:])],
            verbose=False
        )

        preds_l = m_long.predict(X_te_ls)
        acc     = accuracy_score(y_te_l, preds_l)
        f1_m    = f1_score(y_te_l, preds_l, average='macro', zero_division=0)
        ap_l    = average_precision_score(y_te_l, m_long.predict_proba(X_te_ls)[:, 1])
        ap_s    = average_precision_score(y_te_s, m_short.predict_proba(X_te_ss)[:, 1])

        long_p = m_long.predict_proba(X_te_ls)[:, 1]
        short_p = m_short.predict_proba(X_te_ss)[:, 1]
        signal = np.where(
            (long_p >= 0.5) & (long_p > short_p), 1.0,
            np.where((short_p >= 0.5) & (short_p > long_p), -1.0, 0.0)
        )

        c_te     = close_arr[tei]
        nh       = min(len(signal), len(c_te) - 1)
        fwd_ret  = np.log(c_te[1:nh+1] / c_te[:nh] + 1e-10)
        strat    = signal[:nh] * fwd_ret
        sharpe   = (strat.mean() / (strat.std() + 1e-10) * np.sqrt(252))

        folds.append({
            'fold': fold+1, 'n_train': len(tri), 'n_test': len(tei),
            'accuracy': round(acc, 4), 'f1_macro': round(f1_m, 4),
            'ap_long': round(float(ap_l), 4), 'ap_short': round(float(ap_s), 4),
            'sharpe': round(float(sharpe), 4),
        })
        print(
            f'    Fold {fold+1}  acc={acc:.4f}  f1={f1_m:.4f}  '
            f'ap_long={ap_l:.4f}  ap_short={ap_s:.4f}  sharpe={sharpe:.4f}'
        )

    WF_RESULTS[tf] = folds

print('\n✅ Walk-forward validation complete.')
""",
    )

    # --- Cell 31: walk-forward summary chart ---
    set_code(
        31,
        r"""# ── 6.2  Summary table + chart ───────────────────────────────────────────────
rows = []
for tf, folds in WF_RESULTS.items():
    for f in folds:
        rows.append({'timeframe': tf, **f})
wf_df = pd.DataFrame(rows)

cols_mean = ['accuracy', 'f1_macro', 'ap_long', 'ap_short', 'sharpe']
summary_wf = wf_df.groupby('timeframe')[cols_mean].mean().round(4).reset_index()
print('Walk-forward mean metrics (Sharpe = combined long+short prob signal × 1-bar log return):')
print(summary_wf.to_string(index=False))

fig = px.box(
    wf_df, x='timeframe', y='sharpe', color='timeframe',
    title='Walk-Forward Combined-Signal Sharpe by Timeframe (long+short heads)',
    points='all', template='plotly_dark'
)
fig.show()
fig.write_html(str(REPORT_DIR / 'walk_forward_sharpe.html'))
print('✅ Chart saved.')
""",
    )

    set_code(
        37,
        r"""# ── 7.2  Save models + metadata (versioned folder for local storage) ─────────
import sys
import sklearn, xgboost

# Versioned folder: extract to agent/model_storage/jacksparrow_v5_BTCUSD_YYYY-MM-DD
EXPORT_VERSION = '5.0.0'
EXPORT_DATE = datetime.now().strftime('%Y-%m-%d')
EXPORT_DIR = BASE / 'models' / f'jacksparrow_v5_{CFG.symbol}_{EXPORT_DATE}'
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
print(f'Export folder: {EXPORT_DIR}')

for tf in CFG.timeframes:
    tag = f'{CFG.symbol}_{tf}'
    print(f'  Saving [{tag}] …')

    joblib.dump(ENTRY_LONG_MODELS[tf],   EXPORT_DIR / f'entry_long_model_{tag}.joblib')
    joblib.dump(ENTRY_LONG_SCALERS[tf],  EXPORT_DIR / f'entry_long_scaler_{tag}.joblib')
    joblib.dump(ENTRY_SHORT_MODELS[tf],  EXPORT_DIR / f'entry_short_model_{tag}.joblib')
    joblib.dump(ENTRY_SHORT_SCALERS[tf], EXPORT_DIR / f'entry_short_scaler_{tag}.joblib')

    # Feature names: strict train-serve parity contract.
    if list(FEATS[tf].columns) != list(EXPANDED_FEATURE_LIST):
        raise ValueError(
            f'[{tf}] feature order mismatch before export; train/live parity broken.'
        )
    with open(EXPORT_DIR / f'features_{tag}.json', 'w') as f:
        json.dump({'features': list(EXPANDED_FEATURE_LIST)}, f, indent=2)

    wf_mean = (
        pd.DataFrame(WF_RESULTS[tf])[['accuracy', 'f1_macro', 'ap_long', 'ap_short', 'sharpe']]
        .mean().round(4).to_dict()
    )

    yl = ENTRY_LONG_LABELS[tf]
    ys = ENTRY_SHORT_LABELS[tf]
    label_stats = {
        'n_samples': int(len(yl)),
        'long_positive_rate': round(float(yl.mean()), 4),
        'short_positive_rate': round(float(ys.mean()), 4),
    }

    metadata = {
        'model_name':    f'jacksparrow_{tag}',
        'version':       EXPORT_VERSION,
        'symbol':        CFG.symbol,
        'timeframe':     tf,
        'trained_at':    datetime.now(timezone.utc).isoformat(),
        'dataset_sha256': DATA_HASHES[tf],
        'config_sha256': hashlib.sha256(json.dumps(asdict(CFG), sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16],
        'dataset_range': {
            'from':    str(RAW[tf]['timestamp'].iloc[0]),
            'to':      str(RAW[tf]['timestamp'].iloc[-1]),
            'candles': len(RAW[tf]),
        },
        'training_authority': 'notebook_inline_colab',
        'features':        list(EXPANDED_FEATURE_LIST),
        'features_required': list(EXPANDED_FEATURE_LIST),
        'n_features':      len(EXPANDED_FEATURE_LIST),
        'signal_classes':  {'entry': {'long': {'0': 'NO_LONG', '1': 'LONG'},
                                       'short': {'0': 'NO_SHORT', '1': 'SHORT'}}},
        'train_metrics':   TRAIN_METRICS[tf],
        'walkforward_mean': wf_mean,
        'label_strategy': 'tp_sl_first_hit_fee_aware',
        'label_strategy_notes': (
            'Default: agent-aligned TP/SL (0.6%/0.4%) with extended entry_lookahead_map for more positives. '
            'Alternatives: lower TP/SL in training AND agent env together; hybrid return-based auxiliary targets.'
        ),
        'label_stats': label_stats,
        'RECOMMENDED_LONG_THRESHOLD': 0.50,
        'RECOMMENDED_SHORT_THRESHOLD': 0.50,
        'runtime_threshold_hints': {
            'mtf_entry_min_buy_prob': 0.50,
            'mtf_entry_min_sell_prob': 0.50,
        },
        'exit_policy_note': 'Live agent: TP/SL + trailing + max hold; no ML exit artefact in this export.',
        'config': {
            'entry_tp_pct':     TP_PCT,
            'entry_sl_pct':     SL_PCT,
            'entry_fee_pct':    FEE_PCT,
            'entry_max_bars':   ENTRY_MAX_BARS[tf],
            'seed':             CFG.random_seed,
            'timeframes':       list(CFG.timeframes),
        },
        'library_versions': {
            'python':   sys.version.split()[0],
            'xgboost':  xgboost.__version__,
            'sklearn':  sklearn.__version__,
            'numpy':    np.__version__,
            'pandas':   pd.__version__,
        },
        'artifacts': {
            'entry_long_model':  f'entry_long_model_{tag}.joblib',
            'entry_long_scaler': f'entry_long_scaler_{tag}.joblib',
            'entry_short_model':  f'entry_short_model_{tag}.joblib',
            'entry_short_scaler': f'entry_short_scaler_{tag}.joblib',
            'features':     f'features_{tag}.json',
            'metadata':     f'metadata_{tag}.json',
        }
    }
    with open(EXPORT_DIR / f'metadata_{tag}.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)

    n_files = len(list(EXPORT_DIR.glob(f'*{tag}*')))
    print(f'    ✅ {n_files} artifacts saved for [{tag}]')

print('\n✅ All models exported.')
""",
    )

    # --- Cell 40: summary ---
    set_code(
        40,
        r"""# ── 7.5  Training summary ─────────────────────────────────────────────────────
print('\n' + '='*70)
print('🏴‍☠️  JackSparrow v5 — Training Complete')
print('='*70)
print(f'Symbol:       {CFG.symbol}')
print(f'Timeframes:   {CFG.timeframes}')
print(f'Models saved: {len(list(EXPORT_DIR.glob("*.joblib")))} .joblib files (entry long+short per TF; no ML exit)')
print()
print('Per-timeframe results (WF Sharpe = combined long+short signal proxy):')
hdr = f'  {"TF":<6} {"L_acc":>7} {"L_PR":>7} {"L_F1":>7} {"S_acc":>7} {"S_PR":>7} {"S_F1":>7} {"WF_Sh":>7}'
print(hdr)
print(f'  {"-"*6} {"-"*7} {"-"*7} {"-"*7} {"-"*7} {"-"*7} {"-"*7} {"-"*7}')
for tf in CFG.timeframes:
    m  = TRAIN_METRICS[tf]
    wf = pd.DataFrame(WF_RESULTS[tf])['sharpe'].mean()
    print(
        f'  {tf:<6} {m["entry_long_acc"]:>7.4f} {m["entry_long_pr_auc"]:>7.4f} {m["entry_long_f1"]:>7.4f} '
        f'{m["entry_short_acc"]:>7.4f} {m["entry_short_pr_auc"]:>7.4f} {m["entry_short_f1"]:>7.4f} {wf:>7.4f}'
    )
print()
print(f'ZIP: {zip_path}')
print('Optional: python scripts/trade_simulator.py --csv <ohlcv.csv> --tp 0.006 --sl 0.004')
print('='*70)
""",
    )

    NB_PATH.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Wrote", NB_PATH)


if __name__ == "__main__":
    main()
