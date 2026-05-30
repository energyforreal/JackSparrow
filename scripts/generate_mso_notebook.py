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

**Runtime:** Colab *Runtime → Change runtime type → GPU* if you want CUDA training. Set `MSO_INSTALL_LGB_CUDA=true` before the optional build cell (5–15 min compile). Device: `MSO_DEVICE=auto|cpu|cuda` (see device cell). Default Colab pip LightGBM is **CPU-only** unless you run the CUDA build cell.

**Strict policy:** training validates **raw merged** OI/funding on the 5m grid (not `funding_zscore != 0`, which flags warmup zeros incorrectly).

**Quick smoke test:** `MSO_COLAB_QUICK=true` (smaller history pull).
"""
)

code(
    """%pip install -q \\
    "numpy>=1.24" "pandas>=2.0" "httpx>=0.27" "structlog==23.2.0" \\
    "pydantic>=2.5" "pydantic-settings>=2.1" "python-dotenv>=1.0" \\
    "joblib>=1.3" "scikit-learn>=1.3" "xgboost==2.0.2" "lightgbm==4.1.0" \\
    "matplotlib>=3.7" "requests"
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

md(
    """## Optional: CUDA LightGBM build (GPU runtime)

Standard `pip install lightgbm` on Colab is **CPU-only**. To train on GPU, use a **GPU Colab runtime** and set:

```python
os.environ["MSO_INSTALL_LGB_CUDA"] = "true"
```

Run this cell once per session (compiles from source, ~5–15 min). Leave unset to skip and train on CPU.
"""
)

code(
    """import os
import subprocess
import sys

def _cuda_runtime_available() -> bool:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False

_install_cuda_lgb = os.environ.get("MSO_INSTALL_LGB_CUDA", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
if not _install_cuda_lgb:
    print("MSO_INSTALL_LGB_CUDA not set — skipping CUDA build (CPU LightGBM from pip)")
elif not _cuda_runtime_available():
    print("MSO_INSTALL_LGB_CUDA=true but nvidia-smi failed — use Runtime → GPU, then re-run")
else:
    print("Building LightGBM with USE_CUDA=ON (this may take 5–15 minutes)...")
    subprocess.run(["apt-get", "update", "-qq"], check=False)
    subprocess.run(
        [
            "apt-get",
            "install",
            "-qq",
            "-y",
            "cmake",
            "build-essential",
            "libboost-dev",
            "libboost-system-dev",
            "libboost-filesystem-dev",
        ],
        check=False,
    )
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "lightgbm"], check=False)
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-binary",
            "lightgbm",
            "--config-settings=cmake.define.USE_CUDA=ON",
            "lightgbm>=4.1.0",
        ],
        capture_output=False,
    )
    if build.returncode != 0:
        print("CUDA LightGBM build FAILED — reinstalling CPU wheel")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "lightgbm==4.1.0"],
            check=False,
        )
    else:
        print("CUDA LightGBM build OK — continue to imports + device cells")
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
warnings.filterwarnings("ignore", category=FutureWarning, module=r"sklearn.*")

# Smoke test: smaller pulls (~2-5 min). Full training: leave unset or false.
_QUICK = os.environ.get("MSO_COLAB_QUICK", "false").strip().lower() in ("1", "true", "yes")
if _QUICK:
    print("MSO_COLAB_QUICK=true — using reduced candle targets")
"""
)

md("## Device: CPU / GPU (Colab)")

code(
    """import os
import subprocess

import numpy as np

# auto | cpu | cuda (NVIDIA). OpenCL "gpu" is deprecated on Colab — use cuda after CUDA build.
os.environ.setdefault("MSO_DEVICE", "auto")

def _cuda_visible() -> bool:
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False

def _probe_lgb_cuda() -> bool:
    try:
        import lightgbm as _lgb

        m = _lgb.LGBMClassifier(
            device="cuda",
            n_estimators=2,
            verbose=-1,
            objective="multiclass",
            num_class=2,
        )
        m.fit(np.array([[0.0], [1.0], [2.0]]), np.array([0, 1, 0]))
        return True
    except Exception as exc:
        print("  LightGBM CUDA probe failed:", exc)
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
        if want == "gpu":
            print("WARNING: MSO_DEVICE=gpu (OpenCL) is unreliable on Colab — probing cuda instead")
        if not _probe_lgb_cuda():
            print(
                "WARNING: LightGBM has no working CUDA — using CPU. "
                "Set MSO_INSTALL_LGB_CUDA=true and re-run the CUDA build cell."
            )
            return "cpu", {}
        return "cuda", {}
    # auto
    if has_cuda and _probe_lgb_cuda():
        print("MSO_DEVICE=auto → CUDA (LightGBM CUDA build verified)")
        return "cuda", {}
    if has_cuda:
        print(
            "MSO_DEVICE=auto → CPU (GPU runtime present; pip LightGBM is CPU-only). "
            "For GPU training set MSO_INSTALL_LGB_CUDA=true and run the CUDA build cell."
        )
    else:
        print("MSO_DEVICE=auto → CPU (no GPU runtime)")
    return "cpu", {}

LGB_DEVICE, LGB_DEVICE_KW = resolve_lgb_device()
print("LightGBM device:", LGB_DEVICE, LGB_DEVICE_KW)
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
FUNDING_WARMUP_BARS = int(os.environ.get("MSO_FUNDING_WARMUP_BARS", "48"))


def _merge_funding_to_5m(primary: pd.DataFrame, df_fund: pd.DataFrame) -> pd.Series:
    \"\"\"Backward-asof merge hourly funding onto 5m timestamps (same logic as v43).\"\"\"
    n = len(primary)
    if df_fund is None or df_fund.empty:
        return pd.Series(np.nan, index=range(n))
    prim_ts = pd.to_datetime(primary["timestamp"], utc=True)
    ff = df_fund.copy()
    ff["_fts"] = pd.to_datetime(ff["timestamp"], utc=True)
    fr_col = "funding_rate" if "funding_rate" in ff.columns else "close"
    aux = pd.DataFrame(
        {"_fts": ff["_fts"], "fr": pd.to_numeric(ff[fr_col], errors="coerce")}
    ).sort_values("_fts")
    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
    merged = pd.merge_asof(left, aux, left_on="ts", right_on="_fts", direction="backward")
    return merged.sort_values("_ord")["fr"].reset_index(drop=True)


def _merge_oi_contracts(primary: pd.DataFrame, df_oi: pd.DataFrame) -> pd.Series:
    n = len(primary)
    if df_oi is None or df_oi.empty or "oi_contracts" not in df_oi.columns:
        return pd.Series(np.nan, index=range(n))
    prim_ts = pd.to_datetime(primary["timestamp"], utc=True)
    aux = df_oi.copy()
    aux["_ts"] = pd.to_datetime(aux["timestamp"], utc=True)
    aux["oi_contracts"] = pd.to_numeric(aux["oi_contracts"], errors="coerce")
    aux = aux.sort_values("_ts").drop_duplicates(subset=["_ts"], keep="last")
    left = pd.DataFrame({"ts": prim_ts, "_ord": np.arange(n, dtype=int)}).sort_values("ts")
    merged = pd.merge_asof(
        left,
        aux[["_ts", "oi_contracts"]],
        left_on="ts",
        right_on="_ts",
        direction="backward",
    )
    return merged.sort_values("_ord")["oi_contracts"].reset_index(drop=True)


assert len(df_5m) >= MIN_CANDLES_5M, f"Insufficient OHLCV: {len(df_5m)} < {MIN_CANDLES_5M}"
assert not df_oi_hist.empty and len(df_oi_hist) >= int(MIN_CANDLES_5M * 0.90), (
    f"Insufficient OI history: {len(df_oi_hist)}"
)
assert len(df_funding) > 0, "Funding data empty"

# Raw-source coverage on 5m grid (before feature engineering)
_fund_raw = _merge_funding_to_5m(df_5m, df_funding)
_oi_raw = _merge_oi_contracts(df_5m, df_oi_hist)
_post = slice(FUNDING_WARMUP_BARS, None)
_fund_cov_raw = float(_fund_raw.iloc[_post].notna().mean())
_oi_cov_raw = float((_oi_raw.iloc[_post] > 0).mean())
print(
    f"Raw data coverage (post-warmup {FUNDING_WARMUP_BARS} bars): "
    f"funding={_fund_cov_raw:.1%} oi_contracts={_oi_cov_raw:.1%}"
)
assert _fund_cov_raw >= MIN_REAL_FUND_FRACTION, (
    f"Funding merge coverage too low: {_fund_cov_raw:.1%} < {MIN_REAL_FUND_FRACTION:.0%}. "
    "Extend FUNDING_LOOKBACK_HOURS or check FUNDING:{symbol} API."
)
assert _oi_cov_raw >= MIN_REAL_OI_FRACTION, (
    f"OI merge coverage too low: {_oi_cov_raw:.1%} < {MIN_REAL_OI_FRACTION:.0%}. "
    "Check OI:{symbol} candle fetch."
)

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
close_series = pd.to_numeric(df_5m["close"], errors="coerce").iloc[: len(df_feat)].reset_index(drop=True)
df_feat = df_feat.reset_index(drop=True)

feat_cols = [c for c in MSO_FEATURE_COLS if c in df_feat.columns]
missing_cols = [c for c in MSO_FEATURE_COLS if c not in df_feat.columns]
if missing_cols:
    raise RuntimeError(f"MSO missing feature columns: {missing_cols[:8]}")

keep = df_feat[feat_cols].notna().all(axis=1)
df_feat = df_feat.loc[keep].reset_index(drop=True)
close = close_series.loc[keep].reset_index(drop=True)

# Diagnostic only — do NOT gate on zscore==0 (v43 fills warmup with 0.0)
_zscore_zero_frac = float((df_feat["funding_zscore"] == 0).mean()) if "funding_zscore" in df_feat.columns else 0.0
print(
    "Clean training rows:", len(df_feat),
    "features:", len(feat_cols),
    f"(funding_zscore==0 on { _zscore_zero_frac:.1%} rows — warmup/flat funding, OK if raw coverage passed)",
)
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

df_train = df_feat.iloc[:split_idx].copy().reset_index(drop=True)
df_val = df_feat.iloc[split_idx:].copy().reset_index(drop=True)
close_train = close.iloc[:split_idx].reset_index(drop=True)
close_val = close.iloc[split_idx:].reset_index(drop=True)

bundle_dict: dict = {}
label_encoders: dict = {}
class_orders: dict = {}
f1_scores: dict = {}
LGB_DEVICE_USED = LGB_DEVICE


def _is_lgb_device_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("cuda", "cudap", "gpu tree learner", "opencl"))


def _fit_classifier(X_tr, y_tr, X_va, y_va, n_class: int):
    global LGB_DEVICE_USED
    callbacks = []
    eval_set = None
    tr_u = set(np.unique(y_tr))
    va_u = set(np.unique(y_va)) if len(y_va) else set()
    # Early stopping requires every val class to appear in train (LightGBM/sklearn check)
    if len(X_va) >= 50 and len(va_u) >= 2 and va_u.issubset(tr_u):
        eval_set = [(X_va, y_va)]
        callbacks = [lgb.early_stopping(50, verbose=False)]
    elif len(va_u - tr_u) > 0:
        missing = sorted(va_u - tr_u)
        print(f"  note: val classes {missing} absent in train — training without early stopping")

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
        LGB_DEVICE_USED = device
        return clf
    except Exception as exc:
        if device == "cpu" or not _is_lgb_device_error(exc):
            raise
        print(f"LightGBM device={device} failed ({exc!r}); retrying on CPU")
        clf = _make_clf("cpu")
        clf.fit(
            X_tr,
            y_tr,
            eval_set=eval_set,
            callbacks=callbacks if eval_set else None,
        )
        LGB_DEVICE_USED = "cpu"
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
            print(hk, dim, "val F1", round(f1, 4), "device", LGB_DEVICE_USED)
        else:
            f1_scores[hk][dim] = None
            print(hk, dim, "val skipped (insufficient val rows)")

print("Training completed on device:", LGB_DEVICE_USED)

# Export gate (primary horizons)
for hk in ("scalp_10m", "intraday_30m"):
    for dim in MSO_STATE_DIMENSIONS:
        sc = f1_scores.get(hk, {}).get(dim)
        if sc is not None and sc < MIN_F1_EXPORT:
            print(f"WARNING: {hk}/{dim} F1 {sc:.3f} below MIN_F1_EXPORT {MIN_F1_EXPORT}")
"""
)

md(
    """## Post-train validation (holdout evaluation)

**Not a live trading backtest** — this section evaluates the trained MSO bundle on the chronological validation split (same data as training F1):

1. **F1 summary table** — all 24 heads (6 dimensions × 4 horizons).
2. **Trend regime confusion matrix** — primary horizons `scalp_10m` and `intraday_30m`.
3. **Sample oracle rows** — decoded predictions vs actual labels on recent validation bars.
4. **Regime-direction simulation** — maps `intraday_30m` trend predictions to long/short/flat and scores forward returns (illustrates how the agent interprets MSO; not a production P&L claim).

Compare with v43 notebook §4d, which runs regression correlation + simulated validation P&L on return heads.
"""
)

code(
    """from sklearn.metrics import classification_report, confusion_matrix

mso_bundle_eval = MarketStateBundleExport(
    horizon_models=bundle_dict,
    feature_cols=feat_cols,
    state_dimensions=MSO_STATE_DIMENSIONS,
    label_encoders=label_encoders,
    class_orders=class_orders,
    training_metadata={"f1_scores": f1_scores},
)


def _label_from_code(hk: str, dim: str, code) -> str:
    order = class_orders.get(f"{hk}:{dim}") or classes_for_dimension(dim)
    idx = int(code)
    if 0 <= idx < len(order):
        return str(order[idx])
    return str(code)


def _trend_position(label: str) -> int:
    if label in ("STRONG_BULL", "WEAK_BULL"):
        return 1
    if label in ("STRONG_BEAR", "WEAK_BEAR"):
        return -1
    return 0


# --- 1) F1 summary table ---
_rows = []
for hk in HORIZON_MAP:
    for dim in MSO_STATE_DIMENSIONS:
        sc = f1_scores.get(hk, {}).get(dim)
        _rows.append({"horizon": hk, "dimension": dim, "val_f1": sc})
summary_df = pd.DataFrame(_rows)
print("=" * 72)
print("MSO validation F1 (chronological holdout, weighted)")
print("=" * 72)
print(summary_df.pivot(index="dimension", columns="horizon", values="val_f1").round(4).to_string())

# --- 2) Trend regime confusion matrices ---
for _hk in ("scalp_10m", "intraday_30m"):
    _dim = "trend_regime"
    if _hk not in bundle_dict or _dim not in bundle_dict[_hk]:
        print(f"SKIP confusion {_hk}/{_dim}: model missing")
        continue
    _fb = HORIZON_MAP[_hk]
    _classes = list(classes_for_dimension(_dim))
    _labels, _ = build_mso_label(df_feat, close, _dim, _fb)
    _y_val = _labels.iloc[split_idx:].reset_index(drop=True)
    _m = _y_val.notna() & _y_val.astype(str).isin(_classes)
    if int(_m.sum()) < 20:
        print(f"SKIP confusion {_hk}/{_dim}: too few val rows")
        continue
    _X = df_val.loc[_m, feat_cols].to_numpy(dtype=np.float64)
    _pred = bundle_dict[_hk][_dim].predict(_X)
    _y_true = _y_val.loc[_m].astype(str).values
    _y_pred = np.array([_label_from_code(_hk, _dim, c) for c in _pred])
    print("\\n", _hk, _dim, "confusion matrix (rows=actual, cols=pred)")
    _cm = confusion_matrix(_y_true, _y_pred, labels=_classes)
    print(pd.DataFrame(_cm, index=_classes, columns=_classes).to_string())
    print(classification_report(_y_true, _y_pred, labels=_classes, zero_division=0))

# --- 3) Sample oracle snapshot (last 8 validation bars, intraday_30m) ---
_EVAL_HK = "intraday_30m"
if _EVAL_HK in bundle_dict:
    _snap_rows = []
    _start = max(0, len(df_val) - 8)
    for _i in range(_start, len(df_val)):
        _x = df_val.iloc[[_i]][feat_cols]
        _state = mso_bundle_eval.predict_horizon(_EVAL_HK, _x.values, X_df=_x)
        _row = {
            "bar": _i,
            "trend_pred": _label_from_code(_EVAL_HK, "trend_regime", _state.get("trend_regime")),
        }
        for _dim in MSO_STATE_DIMENSIONS:
            _fb = HORIZON_MAP[_EVAL_HK]
            _lab, _ = build_mso_label(df_feat, close, _dim, _fb)
            _actual = _lab.iloc[split_idx + _i]
            if pd.notna(_actual):
                _row[f"{_dim}_actual"] = str(_actual)
        _snap_rows.append(_row)
    if _snap_rows:
        print("\\nSample MSO oracle (_EVAL_HK, last validation bars):")
        print(pd.DataFrame(_snap_rows).to_string(index=False))

# --- 4) Regime-direction simulation (intraday_30m trend → forward return) ---
_SIM_HK = "intraday_30m"
_SIM_DIM = "trend_regime"
if _SIM_HK in bundle_dict and _SIM_DIM in bundle_dict[_SIM_HK]:
    _fb = HORIZON_MAP[_SIM_HK]
    _classes = list(classes_for_dimension(_SIM_DIM))
    _trend_lab, _ = build_mso_label(df_feat, close, _SIM_DIM, _fb)
    _y_val = _trend_lab.iloc[split_idx:].reset_index(drop=True)
    _m = _y_val.notna() & _y_val.astype(str).isin(_classes)
    _X = df_val.loc[_m, feat_cols].to_numpy(dtype=np.float64)
    _close_v = close_val.loc[_m].reset_index(drop=True)
    _fwd = (_close_v.shift(-_fb) / _close_v - 1.0).iloc[: len(_X) - _fb]
    _pred = bundle_dict[_SIM_HK][_SIM_DIM].predict(_X[: len(_fwd)])
    _pos = np.array([_trend_position(_label_from_code(_SIM_HK, _SIM_DIM, c)) for c in _pred])
    _round_trip = float(os.environ.get("MSO_ROUND_TRIP_COST_PCT", "0.0012"))
    _gross = np.where(_pos == 1, _fwd.values, np.where(_pos == -1, -_fwd.values, 0.0))
    _entries = np.diff(np.r_[0, _pos]) != 0
    _net = _gross.copy()
    _net[_entries & (_pos != 0)] -= _round_trip / 2.0
    _net[_entries & (np.r_[0, _pos[:-1]] != 0)] -= _round_trip / 2.0
    _active = _pos != 0
    _hit = float((_gross[_active] > 0).mean()) if _active.any() else 0.0
    _cum = np.cumsum(_net)
    _total = float(_cum[-1]) if len(_cum) else 0.0
    _peak = np.maximum.accumulate(_cum) if len(_cum) else np.array([0.0])
    _max_dd = float(np.min(_cum - _peak)) if len(_cum) else 0.0
    print("\\n" + "=" * 72)
    print(f"Regime-direction simulation — {_SIM_HK} / {_SIM_DIM} (n={len(_fwd)}, fb={_fb})")
    print("=" * 72)
    print(f"  Active bars: {int(_active.sum())} / {len(_pos)} ({100*_active.mean():.1f}%)")
    print(f"  Direction hit rate (gross, active only): {_hit:.1%}")
    print(f"  Total net return (sum): {_total * 100:.2f}%")
    print(f"  Max drawdown (net cum): {_max_dd * 100:.2f}%")
    print(f"  Round-trip cost assumed: {_round_trip:.4%} per entry/exit")
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 3))
        ax.plot(_cum * 100.0, color="#1f77b4", linewidth=1.2)
        ax.set_title(f"MSO regime sim cumulative net return — {_SIM_HK}")
        ax.set_xlabel("Validation bar")
        ax.set_ylabel("Cumulative return (%)")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()
    except ImportError:
        print("  (install matplotlib for cumulative return chart)")
else:
    print("SKIP regime simulation: trend_regime head missing for", _SIM_HK)
"""
)

md("## Export artifacts")

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
        "lgb_device_requested": LGB_DEVICE,
        "lgb_device_used": LGB_DEVICE_USED,
        "raw_funding_coverage": _fund_cov_raw,
        "raw_oi_coverage": _oi_cov_raw,
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
    "training_device_requested": LGB_DEVICE,
    "training_device_used": LGB_DEVICE_USED,
    "raw_funding_coverage": _fund_cov_raw,
    "raw_oi_coverage": _oi_cov_raw,
    "training_date": datetime.now(timezone.utc).isoformat(),
}
meta_path = EXPORT_DIR / "metadata_mso_v50.json"
meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print("Exported:", artifact_path, meta_path)
print("Device used:", LGB_DEVICE_USED)
print("Run the next cell to download jacksparrow_mso_v50_bundle.zip")
"""
)

code(
    """try:
    from google.colab import files
    import shutil

    zip_path = Path("/content/jacksparrow_mso_v50_bundle.zip")
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=str(EXPORT_DIR))
    print("Created zip:", zip_path, f"({zip_path.stat().st_size / 1e6:.1f} MB)")
    files.download(str(zip_path))
except ImportError:
    print("Not in Colab — artifacts at", EXPORT_DIR)
except Exception as exc:
    print("Colab zip/download failed:", exc)
    print("Artifacts remain at", EXPORT_DIR)
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
