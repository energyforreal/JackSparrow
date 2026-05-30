"""Generate notebooks/jacksparrow_mso_v50_training.ipynb for Colab."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "jacksparrow_mso_v50_training.ipynb"

cells = []


def md(src: str) -> None:
    cells.append(
        {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}
    )


def code(src: str) -> None:
    cells.append(
        {
            "cell_type": "code",
            "metadata": {},
            "source": src.splitlines(keepends=True),
            "outputs": [],
            "execution_count": None,
        }
    )


md(
    """# JackSparrow MSO v50 — Market State Oracle (Delta Exchange India)

Train **multi-horizon market-state classifiers** (not return regression).

| Horizon | Bars | ~Minutes |
|---------|------|----------|
| scalp_10m | 2 | 10m |
| intraday_30m | 6 | 30m |
| trend_1h | 12 | 1h |
| swing_2h | 24 | 2h |

**Data:** `https://api.india.delta.exchange` (public OHLCV, OI, MARK, FUNDING)  
**Agent execution:** Delta India testnet only.

**Runtime:** set `MSO_DEVICE=auto|cpu|gpu|cuda` (see device cell). In Colab: *Runtime → Change runtime type* → GPU for faster LightGBM when CUDA build is available.

**Strict policy:** no synthetic OI/funding fills — training hard-fails if real-data fraction is insufficient.

**Quick smoke test:** `MSO_COLAB_QUICK=true` (smaller history pull).
"""
)

code(
    """%pip install -q \\
    "numpy>=1.24" "pandas>=2.0" "httpx>=0.27" "structlog==23.2.0" \\
    "pydantic>=2.5" "pydantic-settings>=2.1" "python-dotenv>=1.0" \\
    "joblib>=1.3" "scikit-learn>=1.3" "xgboost==2.0.2" "lightgbm==4.1.0" \\
    "requests"
"""
)

md("## Clone repo (`MAJOR-REWORK-2`)")

code(
    """import subprocess
from pathlib import Path

_CLONE = Path("/content/trading-agent")
_URL = "https://github.com/energyforreal/JackSparrow.git"
_BRANCH = "MAJOR-REWORK-2"

def _git(*args):
    subprocess.run(["git", "-C", str(_CLONE), *args], check=True)

if (_CLONE / ".git").is_dir():
    _git("fetch", "origin")
    r = subprocess.run(
        ["git", "-C", str(_CLONE), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    cur = (r.stdout or "").strip()
    if cur != _BRANCH:
        _git("checkout", _BRANCH)
    _git("pull", "origin", _BRANCH)
else:
    subprocess.run(["git", "clone", "--branch", _BRANCH, _URL, str(_CLONE)], check=True)
print("Repo ready on branch", _BRANCH)
"""
)

code(
    """import os
import sys
from pathlib import Path

_MARKER = Path("feature_store/jacksparrow_mso_labels.py")

def _repo_has_marker(root: Path) -> bool:
    return (root / _MARKER).is_file()

candidates = []
if os.environ.get("TRADING_AGENT_ROOT"):
    candidates.append(Path(os.environ["TRADING_AGENT_ROOT"]).resolve())
for p in ("/content/trading-agent", "/content/JackSparrow"):
    candidates.append(Path(p).resolve())
candidates.append(Path.cwd().resolve())

REPO_ROOT = None
for c in candidates:
    if _repo_has_marker(c):
        REPO_ROOT = c
        break

if REPO_ROOT is None:
    raise FileNotFoundError(
        "MSO modules not found. Clone MAJOR-REWORK-2 or set TRADING_AGENT_ROOT to your checkout."
    )

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
print("REPO_ROOT =", REPO_ROOT)
"""
)

md("## Device: CPU / GPU (Colab)")

code(
    """import os
import subprocess

# auto | cpu | gpu (OpenCL) | cuda (NVIDIA, recommended on Colab GPU runtime)
os.environ.setdefault("MSO_DEVICE", "auto")

def _cuda_visible() -> bool:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False

def resolve_lgb_device() -> tuple[str, dict]:
    want = os.environ.get("MSO_DEVICE", "auto").strip().lower()
    has_cuda = _cuda_visible()
    if want == "cpu":
        return "cpu", {}
    if want in ("gpu", "cuda"):
        if not has_cuda:
            print("WARNING: MSO_DEVICE=%s but nvidia-smi failed — using CPU" % want)
            return "cpu", {}
        # LightGBM 4.x: cuda on Colab GPU runtime; gpu = OpenCL fallback
        dev = "cuda" if want == "cuda" else "gpu"
        return dev, {}
    # auto
    if has_cuda:
        print("MSO_DEVICE=auto → CUDA GPU (Colab GPU runtime detected)")
        return "cuda", {}
    print("MSO_DEVICE=auto → CPU")
    return "cpu", {}

LGB_DEVICE, LGB_DEVICE_KW = resolve_lgb_device()
print("LightGBM device:", LGB_DEVICE, LGB_DEVICE_KW)
"""
)

code(
    """import json
import os
import time
import warnings
from datetime import datetime, timezone

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
from sklearn.metrics import f1_score
from sklearn.preprocessing import LabelEncoder

from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_mso_feature_extensions import (
    MSO_FEATURE_COLS,
    build_mso_feature_matrix,
)
from feature_store.jacksparrow_mso_labels import (
    MSO_ARTIFACT_FORMAT,
    MSO_FEATURE_VERSION,
    MSO_MODEL_FAMILY,
    MSO_STATE_DIMENSIONS,
    build_mso_label,
    classes_for_dimension,
    horizon_keys_and_bars,
)
from agent.models.market_state_shims import MarketStateBundleExport

warnings.filterwarnings("ignore", category=UserWarning)

# Smoke test: smaller pulls (~2-5 min). Full training: leave unset or false.
_QUICK = os.environ.get("MSO_COLAB_QUICK", "false").strip().lower() in ("1", "true", "yes")
if _QUICK:
    print("MSO_COLAB_QUICK=true — using reduced candle targets")
"""
)

md("## Delta Exchange India — historical data (public API)")

code(
    """DELTA_BASE = os.environ.get("DELTA_EXCHANGE_BASE_URL", "https://api.india.delta.exchange")
SYMBOL = os.environ.get("DELTA_SYMBOL", "BTCUSD")

if _QUICK:
    TARGET_CANDLES_5M = int(os.environ.get("TARGET_CANDLES_5M", "8000"))
    FUNDING_LOOKBACK_H = int(os.environ.get("FUNDING_LOOKBACK_HOURS", "2000"))
    MIN_CANDLES_5M = int(os.environ.get("MSO_MIN_CANDLES_5M", "5000"))
else:
    TARGET_CANDLES_5M = int(os.environ.get("TARGET_CANDLES_5M", "200000"))
    FUNDING_LOOKBACK_H = int(os.environ.get("FUNDING_LOOKBACK_HOURS", "16000"))
    MIN_CANDLES_5M = int(os.environ.get("MSO_MIN_CANDLES_5M", "100000"))

REQUEST_DELAY_S = float(os.environ.get("DELTA_REQUEST_DELAY_S", "0.35"))
PAGE_SIZE = 2000
MAX_FETCH_RETRIES = 4


def _ts_col(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if "time" not in out.columns:
        raise ValueError("candles missing 'time' column")
    out["timestamp"] = pd.to_datetime(out["time"], unit="s", utc=True)
    return out.sort_values("timestamp").reset_index(drop=True)


def fetch_candles_range(session, symbol, resolution, start_ts, end_ts):
    url = f"{DELTA_BASE}/v2/history/candles"
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "start": int(start_ts),
        "end": int(end_ts),
        "page_size": PAGE_SIZE,
    }
    last_exc = None
    for attempt in range(MAX_FETCH_RETRIES):
        try:
            r = session.get(url, params=params, timeout=45)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(data)
            return pd.DataFrame(data.get("result") or [])
        except Exception as exc:
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Delta fetch failed for {symbol}: {last_exc}") from last_exc


def fetch_5m_history(symbol: str, target_rows: int) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    sec = 300
    end_ts = int(time.time())
    start_ts = end_ts - int(target_rows * sec * 1.15)
    chunk_sec = PAGE_SIZE * sec
    frames, cursor = [], start_ts
    while cursor < end_ts:
        chunk_end = min(end_ts, cursor + chunk_sec)
        df = fetch_candles_range(session, symbol, "5m", cursor, chunk_end)
        if not df.empty:
            frames.append(df)
        cursor = chunk_end
        time.sleep(REQUEST_DELAY_S)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"]).sort_values("time")
    if len(raw) > target_rows:
        raw = raw.iloc[-target_rows:]
    return _ts_col(raw)


def fetch_funding_hourly(symbol: str, lookback_hours: int) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    end_ts = int(time.time())
    start_ts = end_ts - int(lookback_hours * 3600)
    frames, cursor = [], start_ts
    while cursor < end_ts:
        chunk_end = min(end_ts, cursor + PAGE_SIZE * 3600)
        df = fetch_candles_range(session, f"FUNDING:{symbol}", "1h", cursor, chunk_end)
        if not df.empty:
            frames.append(df)
        cursor = chunk_end
        time.sleep(REQUEST_DELAY_S)
    if not frames:
        return pd.DataFrame(columns=["timestamp", "funding_rate"])
    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"]).sort_values("time")
    raw["timestamp"] = pd.to_datetime(raw["time"], unit="s", utc=True)
    raw["funding_rate"] = pd.to_numeric(raw["close"], errors="coerce")
    return raw[["timestamp", "funding_rate"]].reset_index(drop=True)


print("Fetching 5m OHLCV ...")
df_5m = fetch_5m_history(SYMBOL, TARGET_CANDLES_5M)
if df_5m.empty:
    raise RuntimeError("OHLCV fetch returned no rows — check symbol and Delta API")

print("Fetching MARK:...", SYMBOL)
df_mark = fetch_5m_history(f"MARK:{SYMBOL}", TARGET_CANDLES_5M)
print("Fetching funding ...")
df_funding = fetch_funding_hourly(SYMBOL, FUNDING_LOOKBACK_H)
print("5m rows:", len(df_5m), "funding rows:", len(df_funding))

from feature_store.jacksparrow_v43_oi_history import oi_candles_to_ticker_frame

print("Fetching OI:...", SYMBOL)
_oi_raw = fetch_5m_history(f"OI:{SYMBOL}", TARGET_CANDLES_5M)
df_oi_hist = oi_candles_to_ticker_frame(
    _oi_raw, df_mark=df_mark, df_spot=df_5m, align_to=df_5m,
)
print("OI history rows:", len(df_oi_hist))
"""
)

code(
    """MIN_REAL_OI_FRACTION = float(os.environ.get("MSO_MIN_REAL_OI_FRACTION", "0.95"))
MIN_REAL_FUND_FRACTION = float(os.environ.get("MSO_MIN_REAL_FUND_FRACTION", "0.85"))

assert len(df_5m) >= MIN_CANDLES_5M, f"Insufficient OHLCV: {len(df_5m)} < {MIN_CANDLES_5M}"
assert not df_oi_hist.empty and len(df_oi_hist) >= int(MIN_CANDLES_5M * 0.90), (
    f"Insufficient OI history: {len(df_oi_hist)}"
)
assert len(df_funding) > 0, "Funding data empty"

os.environ["V43_ALLOW_EMPTY_OI_FOR_TRAINING"] = "false"
v43_feat = build_v43_feature_matrix(
    df_5m,
    df_funding=df_funding,
    df_oi=df_oi_hist,
    df_mark=df_mark,
    for_training=True,
)
if v43_feat.empty:
    raise RuntimeError("v43 feature matrix empty — check OHLCV/OI inputs")

df_feat = build_mso_feature_matrix(v43_feat, df_ohlcv=df_5m)
# Align close to feature rows before dropna (critical for label builders)
close_series = pd.to_numeric(df_5m["close"], errors="coerce").iloc[: len(df_feat)].reset_index(drop=True)
df_feat = df_feat.reset_index(drop=True)

feat_cols = [c for c in MSO_FEATURE_COLS if c in df_feat.columns]
missing_cols = [c for c in MSO_FEATURE_COLS if c not in df_feat.columns]
if missing_cols:
    raise RuntimeError(f"MSO missing feature columns: {missing_cols[:8]}")

keep = df_feat[feat_cols].notna().all(axis=1)
df_feat = df_feat.loc[keep].reset_index(drop=True)
close = close_series.loc[keep].reset_index(drop=True)

oi_real = (df_feat["oi_zscore"].notna() & (df_feat["oi_zscore"] != 0)).mean()
fund_real = (df_feat["funding_zscore"].notna() & (df_feat["funding_zscore"] != 0)).mean()
assert oi_real >= MIN_REAL_OI_FRACTION, f"OI synthetic too high: {1 - oi_real:.1%}"
assert fund_real >= MIN_REAL_FUND_FRACTION, f"Funding synthetic too high: {1 - fund_real:.1%}"

print("Clean training rows:", len(df_feat), "features:", len(feat_cols))
"""
)

code(
    """HORIZON_MAP = horizon_keys_and_bars()
VAL_FRAC = float(os.environ.get("MSO_VALIDATION_FRACTION", "0.20"))
MIN_TRAIN_ROWS = int(os.environ.get("MSO_MIN_TRAIN_ROWS", "5000"))
MIN_F1_EXPORT = float(os.environ.get("MSO_MIN_F1_EXPORT", "0.35"))

split_idx = int(len(df_feat) * (1.0 - VAL_FRAC))
if split_idx < MIN_TRAIN_ROWS:
    raise RuntimeError(f"Too few train rows after split: {split_idx}")

df_train = df_feat.iloc[:split_idx].copy()
df_val = df_feat.iloc[split_idx:].copy()

bundle_dict: dict = {}
label_encoders: dict = {}
class_orders: dict = {}
f1_scores: dict = {}

def _fit_classifier(X_tr, y_tr, X_va, y_va, n_class: int):
    callbacks = []
    eval_set = None
    if len(X_va) >= 50 and len(np.unique(y_va)) >= 2:
        eval_set = [(X_va, y_va)]
        callbacks = [lgb.early_stopping(50, verbose=False)]

    def _make_clf(device: str):
        return lgb.LGBMClassifier(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=63,
            class_weight="balanced",
            objective="multiclass",
            num_class=n_class,
            random_state=42,
            verbose=-1,
            device=device,
            **LGB_DEVICE_KW,
        )

    device = LGB_DEVICE
    try:
        clf = _make_clf(device)
        clf.fit(
            X_tr,
            y_tr,
            eval_set=eval_set,
            callbacks=callbacks if eval_set else None,
        )
        return clf
    except Exception as exc:
        if device == "cpu":
            raise
        print(f"LightGBM device={device} failed ({exc!r}); retrying on CPU")
        clf = _make_clf("cpu")
        clf.fit(
            X_tr,
            y_tr,
            eval_set=eval_set,
            callbacks=callbacks if eval_set else None,
        )
        return clf


for hk, fb in HORIZON_MAP.items():
    bundle_dict[hk] = {}
    f1_scores[hk] = {}
    for dim in MSO_STATE_DIMENSIONS:
        labels, _stats = build_mso_label(df_feat, close, dim, fb)
        classes = list(classes_for_dimension(dim))
        n_class = len(classes)

        y_train = labels.iloc[:split_idx].reset_index(drop=True)
        y_val = labels.iloc[split_idx:].reset_index(drop=True)

        m_tr = y_train.notna() & y_train.astype(str).isin(classes)
        if int(m_tr.sum()) < 100:
            print(f"SKIP {hk}/{dim}: too few train labels ({int(m_tr.sum())})")
            continue

        le = LabelEncoder()
        le.fit(classes)
        X_tr = df_train.loc[m_tr, feat_cols].to_numpy(dtype=np.float64)
        y_tr = le.transform(y_train.loc[m_tr].astype(str))

        m_va = y_val.notna() & y_val.astype(str).isin(classes)
        X_va = df_val.loc[m_va, feat_cols].to_numpy(dtype=np.float64) if m_va.any() else np.empty((0, len(feat_cols)))
        y_va = le.transform(y_val.loc[m_va].astype(str)) if m_va.any() else np.array([], dtype=int)

        model = _fit_classifier(X_tr, y_tr, X_va, y_va, n_class)
        bundle_dict[hk][dim] = model
        label_encoders[f"{hk}:{dim}"] = {c: int(i) for i, c in enumerate(le.classes_)}
        class_orders[f"{hk}:{dim}"] = tuple(classes)

        if len(y_va) >= 10:
            pred = model.predict(X_va)
            f1 = float(
                f1_score(
                    y_va,
                    pred,
                    average="weighted",
                    labels=list(range(n_class)),
                    zero_division=0,
                )
            )
            f1_scores[hk][dim] = f1
            print(hk, dim, "val F1", round(f1, 4), "device", LGB_DEVICE)
        else:
            f1_scores[hk][dim] = None
            print(hk, dim, "val skipped (insufficient val rows)")

# Export gate (primary horizons)
for hk in ("scalp_10m", "intraday_30m"):
    for dim in MSO_STATE_DIMENSIONS:
        sc = f1_scores.get(hk, {}).get(dim)
        if sc is not None and sc < MIN_F1_EXPORT:
            print(f"WARNING: {hk}/{dim} F1 {sc:.3f} below MIN_F1_EXPORT {MIN_F1_EXPORT}")
"""
)

code(
    """EXPORT_DIR = Path(os.environ.get("MSO_EXPORT_DIR", "/content/mso_export"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

mso_bundle = MarketStateBundleExport(
    horizon_models=bundle_dict,
    feature_cols=feat_cols,
    state_dimensions=MSO_STATE_DIMENSIONS,
    label_encoders=label_encoders,
    class_orders=class_orders,
    training_metadata={
        "f1_scores": f1_scores,
        "lgb_device": LGB_DEVICE,
    },
)
artifact_path = EXPORT_DIR / "model_artifact_mso_v50.pkl"
joblib.dump(mso_bundle, artifact_path)

metadata = {
    "model_family": MSO_MODEL_FAMILY,
    "artifact_format": MSO_ARTIFACT_FORMAT,
    "compatible_feature_version": MSO_FEATURE_VERSION,
    "model_name": "jacksparrow_mso_v50_BTCUSD",
    "version": "v50",
    "symbol": SYMBOL,
    "features": feat_cols,
    "feature_count": len(feat_cols),
    "state_dimensions": list(MSO_STATE_DIMENSIONS),
    "horizon_keys": list(HORIZON_MAP.keys()),
    "f1_scores": f1_scores,
    "training_device": LGB_DEVICE,
    "training_date": datetime.now(timezone.utc).isoformat(),
}
meta_path = EXPORT_DIR / "metadata_mso_v50.json"
meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print("Exported:", artifact_path, meta_path)
"""
)

code(
    """try:
    from google.colab import files

    files.download(str(artifact_path))
    files.download(str(meta_path))
except ImportError:
    print("Not in Colab — artifacts at", EXPORT_DIR)
"""
)

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "colab": {"provenance": []},
        "accelerator": "GPU",
    },
    "cells": cells,
}
OUT.write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("Wrote", OUT)
