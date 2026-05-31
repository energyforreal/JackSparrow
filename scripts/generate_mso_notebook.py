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
    """# Verify pulled commit and key MSO flags exist in repo (restart runtime if stale).
import subprocess
from pathlib import Path

_repo = Path("/content/trading-agent")
_r = subprocess.run(
    ["git", "-C", str(_repo), "log", "-1", "--oneline"],
    capture_output=True,
    text=True,
    check=True,
)
print("Git HEAD:", (_r.stdout or "").strip())
for _rel in (
    "feature_store/jacksparrow_mso_labels.py",
    "scripts/generate_mso_notebook.py",
    "agent/models/market_state_shims.py",
):
    _p = _repo / _rel
    print("  ok" if _p.is_file() else "  MISSING", _rel)
_labels = _repo / "feature_store/jacksparrow_mso_labels.py"
if _labels.is_file():
    _txt = _labels.read_text(encoding="utf-8")
    for _needle in ("collapse_trend_regime_labels", "train_quantile_adaptive"):
        if _needle not in _txt:
            print(f"  WARNING: {_needle!r} not in jacksparrow_mso_labels.py — git pull may be stale")
_shims = _repo / "agent/models/market_state_shims.py"
if _shims.is_file() and "_resolve_head_columns" not in _shims.read_text(encoding="utf-8"):
    print("  WARNING: market_state_shims missing per-head feature resolve — restart runtime after pull")
print("If you pulled mid-session, use Runtime → Restart session before training.")
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
from pathlib import Path
from typing import Optional

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
from sklearn.metrics import balanced_accuracy_score, f1_score, recall_score
from sklearn.calibration import CalibratedClassifierCV
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
    collapse_trend_regime_labels,
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
MIN_CLASS_COUNT = int(os.environ.get("MSO_MIN_CLASS_COUNT", "50"))
MSO_MIN_F1_MACRO = float(os.environ.get("MSO_MIN_F1_MACRO", "0.40"))
MSO_MIN_BALANCED_ACC = float(os.environ.get("MSO_MIN_BALANCED_ACC", "0.35"))
MSO_MIN_F1_MACRO_TREND = float(os.environ.get("MSO_MIN_F1_MACRO_TREND", "0.50"))
MSO_BLOCK_EXPORT_ON_FAIL = os.environ.get("MSO_BLOCK_EXPORT_ON_FAIL", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
MSO_CALIBRATE = os.environ.get("MSO_CALIBRATE", "false").strip().lower() in ("1", "true", "yes")
MSO_USE_CLASS_WEIGHT = os.environ.get("MSO_USE_CLASS_WEIGHT", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
MSO_CLASS_WEIGHT_MAJORITY = float(os.environ.get("MSO_CLASS_WEIGHT_MAJORITY", "0.60"))
MSO_TREND_3CLASS = os.environ.get("MSO_TREND_3CLASS", "true").strip().lower() in ("1", "true", "yes")
MSO_TREND_EXCLUDED_FEATURES = tuple(
    x.strip()
    for x in os.environ.get("MSO_TREND_EXCLUDED_FEATURES", "adx_14,trend_mom,hurst_60").split(",")
    if x.strip()
)
MSO_GATE_SCOPE = os.environ.get("MSO_GATE_SCOPE", "policy").strip().lower()
POLICY_HORIZONS = ("intraday_30m",)
POLICY_DIMENSIONS = ("liquidity_condition", "trend_regime", "breakout_state")
PRIMARY_HORIZONS = ("scalp_10m", "intraday_30m")
_RARE_CLASS_WATCH = (
    "FAKE_BREAKOUT",
    "LIQ_SWEEP_ACTIVE",
    "BULL",
    "BEAR",
    "STRONG_BULL",
    "STRONG_BEAR",
    "STOP_HUNT_ENV",
)

MAX_FORWARD_BARS = max(HORIZON_MAP.values())
GAP = int(os.environ.get("MSO_SPLIT_GAP_BARS", str(MAX_FORWARD_BARS)))
split_idx = int(len(df_feat) * (1.0 - VAL_FRAC))
train_end_idx = split_idx - GAP
if train_end_idx < MIN_TRAIN_ROWS:
    raise RuntimeError(
        f"Too few train rows after purge gap: {train_end_idx} (gap={GAP}, split={split_idx})"
    )
print(
    f"Chronological split: train [0,{train_end_idx}) "
    f"purged [{train_end_idx},{split_idx}) val [{split_idx},{len(df_feat)})"
)

df_train = df_feat.iloc[:train_end_idx].copy().reset_index(drop=True)
df_val = df_feat.iloc[split_idx:].copy().reset_index(drop=True)
close_train = close.iloc[:train_end_idx].reset_index(drop=True)
close_val = close.iloc[split_idx:].reset_index(drop=True)

bundle_dict: dict = {}
label_encoders: dict = {}
class_orders: dict = {}
head_feature_cols: dict = {}
f1_scores: dict = {}
class_balance_rows: list = []
export_gate_results: list = []
LGB_DEVICE_USED = LGB_DEVICE


def _class_counts(series: pd.Series, classes: list) -> dict:
    s = series.dropna().astype(str)
    return {c: int((s == c).sum()) for c in classes}


def _lgb_pred_to_labels(model, pred_codes, class_order: tuple) -> np.ndarray:
    order = list(class_order)
    base = model
    if hasattr(model, "calibrated_classifiers_"):
        try:
            base = model.calibrated_classifiers_[0].estimator
        except (IndexError, AttributeError, TypeError):
            pass
    lgb_classes = list(getattr(base, "classes_", []))
    names = []
    for p in np.atleast_1d(pred_codes):
        code = int(p)
        if lgb_classes and code >= len(order):
            if code < len(lgb_classes):
                code = int(lgb_classes[code])
        if 0 <= code < len(order):
            names.append(order[code])
        elif str(code) in order:
            names.append(str(code))
        else:
            names.append(str(code))
    return np.array(names, dtype=object)


def _val_metrics(y_true_str, y_pred_str, classes: list) -> dict:
    yt = np.asarray(y_true_str, dtype=str)
    yp = np.asarray(y_pred_str, dtype=str)
    cls = list(classes)
    counts = np.array([(yt == c).sum() for c in cls], dtype=float)
    total = float(counts.sum())
    majority_baseline = float(counts.max() / total) if total > 0 else 0.0
    recalls = recall_score(yt, yp, labels=cls, average=None, zero_division=0)
    return {
        "f1_weighted": float(
            f1_score(yt, yp, labels=cls, average="weighted", zero_division=0)
        ),
        "f1_macro": float(f1_score(yt, yp, labels=cls, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(yt, yp)),
        "majority_baseline": majority_baseline,
        "pred_mode": str(pd.Series(yp).mode().iloc[0]) if len(yp) else None,
        "true_mode": str(pd.Series(yt).mode().iloc[0]) if len(yt) else None,
        "recall_per_class": {c: float(r) for c, r in zip(cls, recalls)},
    }


def _is_lgb_device_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("cuda", "cudap", "gpu tree learner", "opencl"))


def _class_weight_for_train(train_counts: dict, classes: list) -> Optional[str]:
    if not MSO_USE_CLASS_WEIGHT:
        return None
    total = sum(int(train_counts.get(c, 0)) for c in classes)
    if total <= 0:
        return None
    top_frac = max(int(train_counts.get(c, 0)) for c in classes) / float(total)
    if top_frac >= MSO_CLASS_WEIGHT_MAJORITY:
        return None
    return "balanced"


def _classes_for_training(dim: str) -> list:
    return list(classes_for_dimension(dim, trend_3class=MSO_TREND_3CLASS and dim == "trend_regime"))


def _feature_cols_for_dim(dim: str) -> list:
    if dim == "trend_regime" and MSO_TREND_EXCLUDED_FEATURES:
        return [c for c in feat_cols if c not in MSO_TREND_EXCLUDED_FEATURES]
    return list(feat_cols)


def _gate_horizons_and_dims() -> list:
    if MSO_GATE_SCOPE == "full":
        return [(hk, dim) for hk in PRIMARY_HORIZONS for dim in MSO_STATE_DIMENSIONS]
    return [(hk, dim) for hk in POLICY_HORIZONS for dim in POLICY_DIMENSIONS]


print(
    "Training config:",
    f"MSO_TREND_3CLASS={MSO_TREND_3CLASS}",
    f"MSO_GATE_SCOPE={MSO_GATE_SCOPE}",
    f"MSO_USE_CLASS_WEIGHT={MSO_USE_CLASS_WEIGHT}",
    f"MSO_CALIBRATE={MSO_CALIBRATE}",
    f"trend_features={len(_feature_cols_for_dim('trend_regime'))}/{len(feat_cols)}",
)


def _fit_classifier(X_tr, y_tr, X_va, y_va, n_class: int, *, class_weight=None):
    global LGB_DEVICE_USED
    callbacks = []
    eval_set = None
    tr_u = set(np.unique(y_tr))
    va_u = set(np.unique(y_va)) if len(y_va) else set()
    if len(X_va) >= 50 and len(va_u) >= 2 and va_u.issubset(tr_u):
        eval_set = [(X_va, y_va)]
        callbacks = [lgb.early_stopping(50, verbose=False)]
    elif len(va_u - tr_u) > 0:
        missing = sorted(va_u - tr_u)
        print(f"  note: val classes {missing} absent in train — training without early stopping")

    def _make_clf(device: str):
        kw: dict = {}
        if class_weight is not None:
            kw["class_weight"] = class_weight
        return lgb.LGBMClassifier(
            n_estimators=400,
            learning_rate=0.03,
            num_leaves=63,
            objective="multiclass",
            num_class=n_class,
            random_state=42,
            verbose=-1,
            device=device,
            **kw,
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

    calibrated = False
    if MSO_CALIBRATE and len(X_va) >= 50 and len(set(np.unique(y_va))) >= 2:
        try:
            cal = CalibratedClassifierCV(clf, method="isotonic", cv="prefit")
            cal.fit(X_va, y_va)
            clf = cal
            calibrated = True
        except Exception as exc:
            print(f"  note: calibration failed ({exc!r}); using uncalibrated model")
    return clf, calibrated


def _run_export_gates() -> list:
    failures = []
    for hk, dim in _gate_horizons_and_dims():
        metrics = f1_scores.get(hk, {}).get(dim)
        if not isinstance(metrics, dict):
            failures.append(f"{hk}/{dim}: no metrics (head skipped or insufficient val)")
            continue
        f1m = float(metrics.get("f1_macro", 0.0))
        bal = float(metrics.get("balanced_accuracy", 0.0))
        min_f1 = MSO_MIN_F1_MACRO_TREND if dim == "trend_regime" else MSO_MIN_F1_MACRO
        if f1m < min_f1:
            failures.append(f"{hk}/{dim}: f1_macro {f1m:.3f} < {min_f1:.3f}")
        if bal < MSO_MIN_BALANCED_ACC:
            failures.append(
                f"{hk}/{dim}: balanced_accuracy {bal:.3f} < {MSO_MIN_BALANCED_ACC:.3f}"
            )
    export_gate_results.clear()
    export_gate_results.extend(failures)
    return failures


for hk, fb in HORIZON_MAP.items():
    bundle_dict[hk] = {}
    f1_scores[hk] = {}
    for dim in MSO_STATE_DIMENSIONS:
        labels, label_stats = build_mso_label(
            df_feat, close, dim, fb, train_end_idx=train_end_idx
        )
        if dim == "trend_regime" and MSO_TREND_3CLASS:
            labels = collapse_trend_regime_labels(labels)
        classes = _classes_for_training(dim)
        dim_feat_cols = _feature_cols_for_dim(dim)
        n_class = len(classes)

        y_train = labels.iloc[:train_end_idx].reset_index(drop=True)
        y_val = labels.iloc[split_idx:].reset_index(drop=True)

        m_tr = y_train.notna() & y_train.astype(str).isin(classes)
        m_va = y_val.notna() & y_val.astype(str).isin(classes)
        train_counts = _class_counts(y_train.loc[m_tr], classes)
        val_counts = _class_counts(y_val.loc[m_va], classes)

        if dim == "breakout_state":
            _rare = {c for c in classes if train_counts.get(c, 0) < MIN_CLASS_COUNT}
            if _rare:
                _remap = {c: "NO_BREAKOUT" for c in _rare}
                y_train = y_train.replace(_remap)
                y_val = y_val.replace(_remap)
                m_tr = y_train.notna() & y_train.astype(str).isin(classes)
                m_va = y_val.notna() & y_val.astype(str).isin(classes)
                train_counts = _class_counts(y_train.loc[m_tr], classes)
                val_counts = _class_counts(y_val.loc[m_va], classes)
                if hk in PRIMARY_HORIZONS:
                    print(f"  note: {hk}/{dim} remapped rare train classes {_rare} -> NO_BREAKOUT")

        n_train_classes = sum(1 for c in classes if train_counts.get(c, 0) >= MIN_CLASS_COUNT)
        _cw = _class_weight_for_train(train_counts, classes)
        _train_total = sum(train_counts.values())
        _train_top = max(train_counts, key=train_counts.get) if train_counts else None
        _train_top_pct = (
            float(train_counts[_train_top] / _train_total) if _train_total and _train_top else None
        )
        class_balance_rows.append(
            {
                "horizon": hk,
                "dimension": dim,
                "train_counts": train_counts,
                "val_counts": val_counts,
                "train_top_pct": _train_top_pct,
                "class_weight_used": _cw,
                "single_class_val": sum(1 for v in val_counts.values() if v > 0) <= 1,
            }
        )
        if int(m_tr.sum()) < 100:
            print(f"SKIP {hk}/{dim}: too few train labels ({int(m_tr.sum())})")
            continue
        if n_train_classes < 2:
            print(
                f"SKIP {hk}/{dim}: fewer than 2 train classes with >={MIN_CLASS_COUNT} samples "
                f"(train={train_counts})"
            )
            continue

        if hk in PRIMARY_HORIZONS:
            print(f"{hk} {dim} train: {train_counts} val: {val_counts}")
        val_unique = sum(1 for c in classes if val_counts.get(c, 0) > 0)
        if val_unique <= 1:
            print(f"  WARNING: {hk}/{dim} single-class val — F1 not meaningful")

        le = LabelEncoder()
        le.fit(classes)
        X_tr = df_train.loc[m_tr, dim_feat_cols].to_numpy(dtype=np.float64)
        y_tr = le.transform(y_train.loc[m_tr].astype(str))

        X_va = (
            df_val.loc[m_va, dim_feat_cols].to_numpy(dtype=np.float64)
            if m_va.any()
            else np.empty((0, len(dim_feat_cols)))
        )
        y_va = le.transform(y_val.loc[m_va].astype(str)) if m_va.any() else np.array([], dtype=int)
        y_va_str = y_val.loc[m_va].astype(str).values if m_va.any() else np.array([], dtype=str)

        if hk in PRIMARY_HORIZONS and _cw is None:
            _tot = sum(train_counts.values())
            _top = max(train_counts, key=train_counts.get)
            print(
                f"  note: {hk}/{dim} class_weight=None "
                f"(train top {_top} {_tot and train_counts[_top] / _tot:.0%})"
            )

        model, calibrated = _fit_classifier(
            X_tr, y_tr, X_va, y_va, n_class, class_weight=_cw
        )
        bundle_dict[hk][dim] = model
        label_encoders[f"{hk}:{dim}"] = {c: int(i) for i, c in enumerate(le.classes_)}
        class_orders[f"{hk}:{dim}"] = tuple(classes)
        head_feature_cols[f"{hk}:{dim}"] = list(dim_feat_cols)

        if len(y_va_str) >= 10:
            pred_str = _lgb_pred_to_labels(model, model.predict(X_va), tuple(classes))
            metrics = _val_metrics(y_va_str, pred_str, classes)
            metrics["calibrated"] = calibrated
            metrics["class_weight"] = _cw
            f1_scores[hk][dim] = metrics
            if metrics["f1_macro"] <= metrics["majority_baseline"] + 0.02:
                print(f"  WARNING: {hk}/{dim} trivial/collapsed head (macro F1 ~ majority baseline)")
            if hk in PRIMARY_HORIZONS:
                rpc = metrics.get("recall_per_class", {})
                for rc in _RARE_CLASS_WATCH:
                    if rc in classes and train_counts.get(rc, 0) >= MIN_CLASS_COUNT:
                        print(f"  recall {rc}: {rpc.get(rc, 0.0):.3f}")
            print(
                hk,
                dim,
                "F1w",
                round(metrics["f1_weighted"], 4),
                "F1macro",
                round(metrics["f1_macro"], 4),
                "bal_acc",
                round(metrics["balanced_accuracy"], 4),
                "pred",
                metrics["pred_mode"],
                "true",
                metrics["true_mode"],
                "calibrated",
                calibrated,
                "device",
                LGB_DEVICE_USED,
            )
        else:
            f1_scores[hk][dim] = None
            print(hk, dim, "val skipped (insufficient val rows)")

print("Training completed on device:", LGB_DEVICE_USED)

_gate_failures = _run_export_gates()
if _gate_failures:
    print(f"\\nExport gate failures (scope={MSO_GATE_SCOPE}):")
    for _msg in _gate_failures:
        print(" ", _msg)
else:
    print(f"\\nExport gates passed (scope={MSO_GATE_SCOPE})")
"""
)

md(
    """## Label and class balance audit (primary horizons)

Train/val class counts logged during training for `scalp_10m` and `intraday_30m`. Skipped heads have fewer than two classes with sufficient train samples.
"""
)

code(
    """_audit_rows = []
for row in class_balance_rows:
    if row["horizon"] not in PRIMARY_HORIZONS:
        continue
    tr = row["train_counts"]
    va = row["val_counts"]
    _audit_rows.append(
        {
            "horizon": row["horizon"],
            "dimension": row["dimension"],
            "train_n": sum(tr.values()),
            "val_n": sum(va.values()),
            "train_classes": sum(1 for v in tr.values() if v > 0),
            "val_classes": sum(1 for v in va.values() if v > 0),
            "train_top": max(tr, key=tr.get) if tr else None,
            "val_top": max(va, key=va.get) if va else None,
            "train_top_pct": row.get("train_top_pct"),
            "class_weight_used": row.get("class_weight_used"),
            "SINGLE_CLASS_VAL": row.get("single_class_val", False),
        }
    )
if _audit_rows:
    print(pd.DataFrame(_audit_rows).to_string(index=False))
else:
    print("No class balance rows (run training cell first)")
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

_required = (
    "bundle_dict",
    "feat_cols",
    "head_feature_cols",
    "class_orders",
    "MSO_TREND_3CLASS",
    "_feature_cols_for_dim",
    "_classes_for_training",
    "collapse_trend_regime_labels",
)
_missing = [n for n in _required if n not in globals()]
if _missing:
    raise RuntimeError(
        "Post-train validation requires the training cell first. Missing: "
        + ", ".join(_missing)
    )

# Rebuild per-head feature lists if validation runs without re-training (or old session).
if not head_feature_cols:
    head_feature_cols = {}
    for _hk, _dims in bundle_dict.items():
        for _dim in _dims:
            head_feature_cols[f"{_hk}:{_dim}"] = list(_feature_cols_for_dim(_dim))

_breakout_rare_remap_cache: dict = {}


def _breakout_rare_remap_for_fb(fb: int) -> dict:
    if fb in _breakout_rare_remap_cache:
        return _breakout_rare_remap_cache[fb]
    _brk_classes = list(classes_for_dimension("breakout_state"))
    _brk_lab, _ = build_mso_label(
        df_feat, close, "breakout_state", fb, train_end_idx=train_end_idx
    )
    _brk_tr = _brk_lab.iloc[:train_end_idx]
    _brk_counts = _class_counts(_brk_tr.dropna(), _brk_classes)
    _remap = {
        c: "NO_BREAKOUT" for c in _brk_classes if _brk_counts.get(c, 0) < MIN_CLASS_COUNT
    }
    _breakout_rare_remap_cache[fb] = _remap
    return _remap


def _labels_for_eval(dim: str, fb: int) -> pd.Series:
    _lab, _ = build_mso_label(df_feat, close, dim, fb, train_end_idx=train_end_idx)
    if dim == "trend_regime" and MSO_TREND_3CLASS:
        _lab = collapse_trend_regime_labels(_lab)
    _y = _lab.iloc[split_idx:].reset_index(drop=True)
    if dim == "breakout_state":
        _remap = _breakout_rare_remap_for_fb(fb)
        if _remap:
            _y = _y.replace(_remap)
    return _y


mso_bundle_eval = MarketStateBundleExport(
    horizon_models=bundle_dict,
    feature_cols=feat_cols,
    state_dimensions=MSO_STATE_DIMENSIONS,
    label_encoders=label_encoders,
    class_orders=class_orders,
    head_feature_cols=head_feature_cols,
    training_metadata={"f1_scores": f1_scores},
)


def _trend_position(label: str) -> int:
    if label in ("STRONG_BULL", "WEAK_BULL", "BULL"):
        return 1
    if label in ("STRONG_BEAR", "WEAK_BEAR", "BEAR"):
        return -1
    return 0


# --- 1) Recomputed metrics summary table ---
_rows = []
for hk in HORIZON_MAP:
    for dim in MSO_STATE_DIMENSIONS:
        metrics = f1_scores.get(hk, {}).get(dim)
        if isinstance(metrics, dict):
            _rows.append(
                {
                    "horizon": hk,
                    "dimension": dim,
                    "f1_weighted": metrics.get("f1_weighted"),
                    "f1_macro": metrics.get("f1_macro"),
                    "bal_acc": metrics.get("balanced_accuracy"),
                    "maj_baseline": metrics.get("majority_baseline"),
                }
            )
        else:
            _rows.append(
                {
                    "horizon": hk,
                    "dimension": dim,
                    "f1_weighted": None,
                    "f1_macro": None,
                    "bal_acc": None,
                    "maj_baseline": None,
                }
            )
_recomp_df = pd.DataFrame(_rows)
print("=" * 72)
print("MSO validation metrics (chronological holdout, string labels)")
print("=" * 72)
print(
    _recomp_df.pivot(index="dimension", columns="horizon", values="f1_macro")
    .round(4)
    .to_string()
)
print("\\nBalanced accuracy:")
print(_recomp_df.pivot(index="dimension", columns="horizon", values="bal_acc").round(4).to_string())

# --- 2) Trend regime confusion matrices ---
for _hk in PRIMARY_HORIZONS:
    _dim = "trend_regime"
    if _hk not in bundle_dict or _dim not in bundle_dict[_hk]:
        print(f"SKIP confusion {_hk}/{_dim}: model missing")
        continue
    _fb = HORIZON_MAP[_hk]
    _classes = _classes_for_training(_dim)
    print(f"  (eval classes: {_classes})")
    _y_val = _labels_for_eval(_dim, _fb)
    _m = _y_val.notna() & _y_val.astype(str).isin(_classes)
    if int(_m.sum()) < 20:
        print(f"SKIP confusion {_hk}/{_dim}: too few val rows")
        continue
    _dim_cols = _feature_cols_for_dim(_dim)
    _X = df_val.loc[_m, _dim_cols].to_numpy(dtype=np.float64)
    _model = bundle_dict[_hk][_dim]
    _y_true = _y_val.loc[_m].astype(str).values
    _y_pred = _lgb_pred_to_labels(_model, _model.predict(_X), tuple(_classes))
    print("\\n", _hk, _dim, "confusion matrix (rows=actual, cols=pred)")
    _cm = confusion_matrix(_y_true, _y_pred, labels=_classes)
    print(pd.DataFrame(_cm, index=_classes, columns=_classes).to_string())
    print(classification_report(_y_true, _y_pred, labels=_classes, zero_division=0))
    _mobj = f1_scores.get(_hk, {}).get(_dim)
    if isinstance(_mobj, dict):
        _rpc = _mobj.get("recall_per_class", {})
        _zero = [
            c
            for c in _classes
            if _rpc.get(c, 0.0) == 0.0
            and sum(1 for yt in _y_true if yt == c) >= MIN_CLASS_COUNT
        ]
        if _zero:
            print(f"  ZERO RECALL (val, train-supported): {_zero}")

# --- 3) Sample oracle snapshot (last 8 validation bars, intraday_30m) ---
_EVAL_HK = "intraday_30m"
_EVAL_DIM = "trend_regime"
if _EVAL_HK in bundle_dict:
    _snap_rows = []
    _start = max(0, len(df_val) - 8)
    _has_trend = _EVAL_DIM in bundle_dict.get(_EVAL_HK, {})
    if not _has_trend:
        print(f"Sample oracle: {_EVAL_HK}/{_EVAL_DIM} model missing — trend_pred=N/A")
    for _i in range(_start, len(df_val)):
        _x_full = df_val.iloc[[_i]][feat_cols]
        _state = mso_bundle_eval.predict_horizon(_EVAL_HK, _x_full.values, X_df=_x_full)
        if _has_trend:
            _trend_cols = _feature_cols_for_dim(_EVAL_DIM)
            _x_trend = df_val.iloc[[_i]][_trend_cols]
            _trend_model = bundle_dict[_EVAL_HK][_EVAL_DIM]
            _trend_pred = _lgb_pred_to_labels(
                _trend_model,
                _trend_model.predict(_x_trend.to_numpy(dtype=np.float64)),
                class_orders[f"{_EVAL_HK}:{_EVAL_DIM}"],
            )[0]
        else:
            _trend_pred = "N/A (model missing)"
        _row = {"bar": _i, "trend_pred": _trend_pred}
        for _dim in MSO_STATE_DIMENSIONS:
            _fb = HORIZON_MAP[_EVAL_HK]
            _lab = _labels_for_eval(_dim, _fb)
            _actual = _lab.iloc[_i]
            if pd.notna(_actual):
                _row[f"{_dim}_actual"] = str(_actual)
            if _dim in bundle_dict.get(_EVAL_HK, {}):
                _pred_model = bundle_dict[_EVAL_HK][_dim]
                _dim_cols = _feature_cols_for_dim(_dim)
                _x_dim = df_val.iloc[[_i]][_dim_cols]
                _pred = _lgb_pred_to_labels(
                    _pred_model,
                    _pred_model.predict(_x_dim.to_numpy(dtype=np.float64)),
                    class_orders[f"{_EVAL_HK}:{_dim}"],
                )[0]
                _row[f"{_dim}_pred"] = _pred
        _snap_rows.append(_row)
    if _snap_rows:
        print("\\nSample MSO oracle (_EVAL_HK, last validation bars):")
        print(pd.DataFrame(_snap_rows).to_string(index=False))
else:
    print(f"SKIP sample oracle: {_EVAL_HK} not in bundle_dict")

# --- 4) Regime-direction simulation (intraday_30m trend → forward return) ---
_SIM_HK = "intraday_30m"
_SIM_DIM = "trend_regime"
if _SIM_HK in bundle_dict and _SIM_DIM in bundle_dict[_SIM_HK]:
    _fb = HORIZON_MAP[_SIM_HK]
    _classes = _classes_for_training(_SIM_DIM)
    _y_val = _labels_for_eval(_SIM_DIM, _fb)
    _m = _y_val.notna() & _y_val.astype(str).isin(_classes)
    _sim_cols = _feature_cols_for_dim(_SIM_DIM)
    _X = df_val.loc[_m, _sim_cols].to_numpy(dtype=np.float64)
    _close_v = close_val.loc[_m].reset_index(drop=True)
    _fwd = (_close_v.shift(-_fb) / _close_v - 1.0).iloc[: len(_X) - _fb]
    _sim_model = bundle_dict[_SIM_HK][_SIM_DIM]
    _pred_str = _lgb_pred_to_labels(
        _sim_model, _sim_model.predict(_X[: len(_fwd)]), tuple(_classes)
    )
    _pos = np.array([_trend_position(p) for p in _pred_str])
    _trend_metrics = f1_scores.get(_SIM_HK, {}).get(_SIM_DIM) or {}
    _bal_acc = float(_trend_metrics.get("balanced_accuracy", 0.0))
    _n_pred_classes = len(set(_pred_str))
    _skip_sim = _n_pred_classes <= 1 or _bal_acc < MSO_MIN_BALANCED_ACC
    if _skip_sim:
        print(
            f"\\nSKIP regime simulation: collapsed trend head "
            f"(pred_classes={_n_pred_classes}, bal_acc={_bal_acc:.3f})"
        )
    else:
        _round_trip = float(os.environ.get("MSO_ROUND_TRIP_COST_PCT", "0.0012"))
        _gross = np.where(_pos == 1, _fwd.values, np.where(_pos == -1, -_fwd.values, 0.0))
        _entries = np.diff(np.r_[0, _pos]) != 0
        _net = _gross.copy()
        _net[_entries & (_pos != 0)] -= _round_trip / 2.0
        _net[_entries & (np.r_[0, _pos[:-1]] != 0)] -= _round_trip / 2.0
        _active = _pos != 0
        _flat = _pos == 0
        _hit = float((_gross[_active] > 0).mean()) if _active.any() else 0.0
        _cum_sum = np.cumsum(_net)
        _equity = np.cumprod(1.0 + _net)
        _total_sum = float(_cum_sum[-1]) if len(_cum_sum) else 0.0
        _total_comp = float(_equity[-1] - 1.0) if len(_equity) else 0.0
        _peak = np.maximum.accumulate(_cum_sum) if len(_cum_sum) else np.array([0.0])
        _max_dd = float(np.min(_cum_sum - _peak)) if len(_cum_sum) else 0.0
        print("\\n" + "=" * 72)
        print(f"Regime-direction simulation — {_SIM_HK} / {_SIM_DIM} (n={len(_fwd)}, fb={_fb})")
        print("=" * 72)
        print(f"  Active bars: {int(_active.sum())} / {len(_pos)} ({100*_active.mean():.1f}%)")
        print(f"  Flat bars: {int(_flat.sum())} / {len(_pos)} ({100*_flat.mean():.1f}%)")
        print(f"  Direction hit rate (gross, active only): {_hit:.1%}")
        print(f"  Total net return (sum): {_total_sum * 100:.2f}%")
        print(f"  Total net return (compounded): {_total_comp * 100:.2f}%")
        print(f"  Max drawdown (net sum cum): {_max_dd * 100:.2f}%")
        print(f"  Round-trip cost assumed: {_round_trip:.4%} per entry/exit")
        try:
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 3))
            ax.plot((_equity - 1.0) * 100.0, color="#1f77b4", linewidth=1.2)
            ax.set_title(f"MSO regime sim cumulative net return (compounded) — {_SIM_HK}")
            ax.set_xlabel("Validation bar")
            ax.set_ylabel("Cumulative return (compounded %)")
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

_gate_failures = _run_export_gates()
print(f"Export gate scope: {MSO_GATE_SCOPE} ({len(_gate_horizons_and_dims())} heads)")
if MSO_BLOCK_EXPORT_ON_FAIL and _gate_failures:
    raise RuntimeError(
        "MSO export blocked — export gates failed:\\n"
        + "\\n".join(f"  - {m}" for m in _gate_failures)
        + "\\nSet MSO_BLOCK_EXPORT_ON_FAIL=false to export anyway (debug only)."
    )
if _gate_failures:
    print("WARNING: exporting despite gate failures (MSO_BLOCK_EXPORT_ON_FAIL=false)")

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

mso_bundle = MarketStateBundleExport(
    horizon_models=bundle_dict,
    feature_cols=feat_cols,
    state_dimensions=MSO_STATE_DIMENSIONS,
    label_encoders=label_encoders,
    class_orders=class_orders,
    head_feature_cols=head_feature_cols,
    training_metadata={
        "f1_scores": f1_scores,
        "export_gate_results": export_gate_results,
        "export_gate_scope": MSO_GATE_SCOPE,
        "lgb_device_requested": LGB_DEVICE,
        "lgb_device_used": LGB_DEVICE_USED,
        "raw_funding_coverage": _fund_cov_raw,
        "raw_oi_coverage": _oi_cov_raw,
        "mso_trend_3class": MSO_TREND_3CLASS,
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
    "export_gate_results": export_gate_results,
    "export_gate_scope": MSO_GATE_SCOPE,
    "export_gate_passed": len(export_gate_results) == 0,
    "mso_trend_3class": MSO_TREND_3CLASS,
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
print("Export gate scope:", MSO_GATE_SCOPE)
print("Export gates passed:", len(export_gate_results) == 0)
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
